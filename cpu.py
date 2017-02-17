import debug
import operator
import bus

class REG(bus.BUS_OBJECT):
    def __init__(self, name, size=8, init=0):
        super(REG, self).__init__()
        self.name = name
        self.size = size
        self.value = init
        self.init = init
        self.mask = 2**size-1
        self.half_mask = 2**(size/2)-1

    def reset(self):
        self.value = self.init

    def read(self):
        return self.value

    def write(self, value, mask=None):
        value &= self.mask
        # TODO: split into masked_write and write
        if mask is None:
            self.value = value
        else:
            self.value &= ~mask
            self.value |= value & mask

    def bus_read(self, addr):
        return self.read()

    def bus_write(self, addr, value):
        return self.write(value)

    def incr(self, delta):
        self.value += delta
        self.value &= self.mask

    def flagged_incr(self, delta):
        decr = delta < 0

        if decr:
            carry = -delta > self.value
            half_carry = ((-delta) & self.half_mask) > (self.value & self.half_mask)

        delta &= self.mask

        full = self.value + delta
        half = (self.value & self.half_mask) + (delta & self.half_mask)
        
        self.value = full & self.mask

        if not decr:
            carry = full > self.mask
            half_carry = half > self.half_mask
        return (carry, half_carry)


class FUSED_REG(object):
    def __init__(self, reg_hi, reg_lo):
        self.name = reg_hi.name + reg_lo.name
        self.size = reg_hi.size + reg_lo.size

        self.reg_hi = reg_hi
        self.reg_lo = reg_lo

    def reset(self):
        self.reg_hi.reset()
        self.reg_lo.reset()

    def read(self):
        return self.reg_hi.read() << self.reg_hi.size | self.reg_lo.read()

    def write(self, value, mask = None):
        if mask is None:
            lo_mask = hi_mask = None
        else:
            lo_mask = mask & self.reg_lo.mask
            hi_mask = (mask >> self.reg_lo.size) & self.reg_hi.mask
        # TODO: don't use write method, just reach write in and do it
        self.reg_lo.write(value & self.reg_lo.mask, lo_mask)
        value = value >> self.reg_lo.size
        self.reg_hi.write(value & self.reg_hi.mask, hi_mask)

    def incr(self, delta):
        # TODO: don't hardcode width:
        self.write((self.read()+delta)&0xFFFF)

    def flagged_incr(self, delta):
        decr = delta < 0
        value = self.read()
        # TODO: don't hardcode these:
        mask = 0xFFFF
        half_mask = 0x0FFF

        if decr:
            carry = -delta > value
            half_carry = ((-delta) & half_mask) > (value & half_mask)

        delta &= mask

        full = value + delta
        half = (value & half_mask) + (delta & half_mask)
        
        self.write(full & mask)

        if not decr:
            carry = full > mask
            half_carry = half > half_mask
        return (carry, half_carry)


class IMMEDIATE_REG(object):
    def __init__(self, cpu, size=8):
        if size != 8 and size != 16:
            raise Exception("Bad size")
        self.cpu = cpu
        self.name = "IMMEDIATE_%d" % size
        self.size = size

    def reset(self):
        # TODO: better exception class for this:
        raise Exception("Cannot write to immediate argument")

    def read(self):
        if self.size == 8:
            return self.cpu.bus.read(self.cpu.PC.read()+1)
        else:
            return self.cpu.bus.read_16(self.cpu.PC.read()+1)

    def write(self, value, mask = None):
        # TODO: better exception class for this:
        raise Exception("Cannot write to immediate argument")

    def incr(self, delta):
        # TODO: better exception class for this:
        raise Exception("Cannot write to immediate argument")

    def flagged_incr(self, delta):
        # TODO: better exception class for this:
        raise Exception("Cannot write to immediate argument")


class CPUException(Exception):
    def __init__(self, *args, **kwargs):
        return Exception.__init__(self, *args, **kwargs)


class CPUOpcodeException(CPUException):
    def __init__(self, opcode):
        return CPUException.__init__(self, "Invalid opcode %02X" % opcode)


class CPU(object):
    def __init__(self, bus):
        self.bus = bus

        self.f = 4.194304e6
        self.T_cyc = 1 / self.f # 2.384185791015625e-07

        self._IME = True
        self._stopped = False
        self._halted = False

        for reg in "ABCDEFHL":
            setattr(self, reg, REG(reg))
        self.AF = FUSED_REG(self.A, self.F)
        self.BC = FUSED_REG(self.B, self.C)
        self.DE = FUSED_REG(self.D, self.E)
        self.HL = FUSED_REG(self.H, self.L)

        self.SP = REG("SP", 16, 0xFFFE)
        self.PC = REG("PC", 16, 0x0100)

        # Not part of the ISA, but we'll use these for instructions that operate
        # directly on memory addresses and immediate data
        self.MEM_TMP = REG("MEM_TMP")
        self.IMMEDIATE_8 = IMMEDIATE_REG(self, 8)
        self.IMMEDIATE_16 = IMMEDIATE_REG(self, 16)

        self.F.mask = 0xF0
        self.FLAG = self.F
        self.FLAG_Z = 0b10000000
        self.FLAG_N = 0b01000000
        self.FLAG_H = 0b00100000
        self.FLAG_C = 0b00010000

        # r[6] is supposed to be (HL), but we'll handle that separately
        self.r = [
            self.B, self.C, self.D, self.E,
            self.H, self.L, None, self.A
        ]
        self.rp = [
            self.BC, self.DE, self.HL, self.SP
        ]
        self.rp2 = [
            self.BC, self.DE, self.HL, self.AF
        ]
        self.cc = [
            lambda: (self.FLAG.read() & self.FLAG_Z) == 0, #NZ
            lambda: (self.FLAG.read() & self.FLAG_Z) != 0, #Z
            lambda: (self.FLAG.read() & self.FLAG_C) == 0, #NC
            lambda: (self.FLAG.read() & self.FLAG_C) != 0 #C
        ]
        self.alu = [
            lambda operand, from_memory: self.op_add(operand, from_memory, False, False), # ADD
            lambda operand, from_memory: self.op_add(operand, from_memory, True, False), # ADC
            lambda operand, from_memory: self.op_add(operand, from_memory, False, True), # SUB
            lambda operand, from_memory: self.op_add(operand, from_memory, True, True), # SBC
            lambda operand, from_memory: self.op_bitwise(operand, from_memory, operator.and_), # AND
            lambda operand, from_memory: self.op_bitwise(operand, from_memory, operator.xor), # XOR
            lambda operand, from_memory: self.op_bitwise(operand, from_memory, operator.or_), # OR
            self.op_compare # CP
        ]
        self.rot = [
            lambda dst, from_memory: self.op_rot(dst, from_memory, True, False, True), # RLC
            lambda dst, from_memory: self.op_rot(dst, from_memory, False, False, True), # RRC
            lambda dst, from_memory: self.op_rot(dst, from_memory, True, True, True), # RL
            lambda dst, from_memory: self.op_rot(dst, from_memory, False, True, True), # RR
            lambda dst, from_memory: self.op_shift(dst, from_memory, True, True), # SLA
            lambda dst, from_memory: self.op_shift(dst, from_memory, False, True), # SRA
            self.op_swap,
            lambda dst, from_memory: self.op_shift(dst, from_memory, False, False), # SRL
        ]

        self.reset()

    def reset(self):
        self.A.write(0x01)
        self.F.write(0xB0)
        self.B.write(0x00)
        self.C.write(0x13)
        self.D.write(0x00)
        self.E.write(0xD8)
        self.H.write(0x01)
        self.L.write(0x4D)
        self.SP.write(0xFFFE)

    def op_nop(self):
        self.PC.incr(1)
        return 4

    def op_ld(self, dst, src):
        dst.write(src.read())
        self.PC.incr(1)
        return 4 if dst.size == 8 else 8

    def op_ld_imm_8(self, dst):
        dst.write(self.bus.read(self.PC.read()+1))
        self.PC.incr(2)
        return 8

    def op_ld_imm_16(self, dst):
        dst.write(self.bus.read_16(self.PC.read()+1))
        self.PC.incr(3)
        return 12

    def op_mem_store_indirect(self, addr_reg, src, addr_delta=0, addr_offset=0):
        addr = addr_reg.read()
        addr += addr_offset
        addr &= 0xFFFF
        self.bus.write(addr, src.read())
        if addr_delta != 0:
            addr_reg.incr(addr_delta)
        self.PC.incr(1)
        return 8

    def op_mem_store(self, dst, src, addr_offset=0):
        # TODO: combine this with op_mem_store_indirect - the only real
        # difference is the PC incr at the end
        # TODO: two separate ops use this function, and one uses 8 bit immediate
        # data while the other uses 16. find a nicer way to figure out which
        # to use, rather than testing addr_offset
        addr = dst.read()
        addr += addr_offset
        addr &= 0xFFFF
        self.bus.write(addr, src.read())
        self.PC.incr(1+dst.size/8)
        return 12 if addr_offset != 0 else 16

    def op_mem_store_sp(self):
        self.bus.write_16(self.bus.read_16(self.PC.read()+1), self.SP.read())
        self.PC.incr(3)
        return 20

    def op_mem_store_indirect_imm(self, addr_reg):
        self.bus.write(addr_reg.read(), self.bus.read(self.PC.read()+1))
        self.PC.incr(2)
        return 12

    def op_mem_load(self, dst, addr_offset=0):
        # TODO: two separate ops use this function, and one uses 8 bit immediate
        # data while the other uses 16. find a nicer way to figure out which
        # to use, rather than testing addr_offset
        if addr_offset == 0:
            addr = self.bus.read_16(self.PC.read()+1)
            imm_bytes = 2
            cycles = 16
        else:
            addr = self.bus.read(self.PC.read()+1)
            addr += addr_offset
            imm_bytes = 1
            cycles = 12
        addr &= 0xFFFF
        dst.write(self.bus.read(addr))
        self.PC.incr(1+imm_bytes)
        return cycles

    def op_mem_pop(self, dst):
        dst.write(self.bus.read_16(self.SP.read()))
        self.SP.incr(2)
        self.PC.incr(1)
        return 12

    def op_mem_push(self, src):
        self.SP.incr(-2)
        self.bus.write_16(self.SP.read(), src.read())
        self.PC.incr(1)
        return 16

    def op_mem_load_indirect(self, addr_reg, dst, addr_delta=0, addr_offset=0):
        addr = addr_reg.read()
        addr += addr_offset
        addr &= 0xFFFF
        dst.write(self.bus.read(addr))
        if addr_delta != 0:
            addr_reg.incr(addr_delta)
        self.PC.incr(1)
        return 8

    def op_add_16(self, dst, src):
        (carry, half_carry) = dst.flagged_incr(src.read())

        self.FLAG.write(0, self.FLAG_N)
        self.FLAG.write(0xFF if half_carry else 0x00, self.FLAG_H)
        self.FLAG.write(0xFF if carry else 0x00, self.FLAG_C)

        self.PC.incr(1)
        return 8

    def op_add_sp(self, dst, long_op):
        r8 = self.bus.read(self.PC.read()+1)
        sp = self.SP.read()
        
        half_carry = ((sp & 0x0F) + (r8 & 0x0F)) > 0x0F
        carry = ((sp & 0xFF) + r8) > 0xFF

        if (r8 & 0x80) != 0:
            r8 |= 0xFF00

        self.FLAG.write(0x00, self.FLAG_Z)
        self.FLAG.write(0x00, self.FLAG_N)
        self.FLAG.write(0xFF if half_carry else 0x00, self.FLAG_H)
        self.FLAG.write(0xFF if carry else 0x00, self.FLAG_C)

        dst.write((r8+sp)&0xFFFF)

        self.PC.incr(2)
        return 16 if long_op else 12

    def op_inc_16(self, dst, delta):
        (carry, half_carry) = dst.flagged_incr(delta)
        self.PC.incr(1)
        return 8

    def op_inc_8(self, dst, delta):
        (_, half_carry) = dst.flagged_incr(delta)

        self.FLAG.write(0xFF if half_carry else 0x00, self.FLAG_H)
        self.FLAG.write(0xFF if delta < 0 else 0x00, self.FLAG_N)
        self.FLAG.write(0xFF if dst.read() == 0 else 0x00, self.FLAG_Z)

        self.PC.incr(1)
        return 4

    def op_mem_inc_8(self, addr_reg, delta):
        addr = addr_reg.read()
        self.MEM_TMP.write(self.bus.read(addr))
        self.op_inc_8(self.MEM_TMP, delta)
        self.bus.write(addr, self.MEM_TMP.read())
        return 12

    def op_rot(self, dst, from_memory, left, include_carry, cb_op=False):
        val = dst.read()
        if from_memory:
            val = self.bus.read(val)

        # This is probably a really slow way to do rotates but it's late and
        # I'm tired and this is easy
        val = map(lambda bit: bit=='1', bin(val)[2:].rjust(8))
        if include_carry:
            carry = (self.FLAG.read() & self.FLAG_C) != 0
            val.insert(0, carry)

        if left:
            rot_bit = val[0]
            val = val[1:] + [rot_bit]
        else:
            rot_bit = val[-1]
            val = [rot_bit] + val[:-1]

        if include_carry:
            self.FLAG.write(0xFF if val[0] else 0x00, self.FLAG_C)
        else:
            self.FLAG.write(0xFF if rot_bit else 0x00, self.FLAG_C)

        val = reduce(lambda x,y:y|(x<<1),val)
        val = val & 0xFF

        if from_memory:
            self.bus.write(dst.read(), val)
        else:
            dst.write(val)

        # Set *almost* according to the miscellanea at:
        # https://github.com/simias/gb-rs/blob/master/README.md
        # but ignoring the suggestion that Z shouldn't be modified in RLCA
        if cb_op:
            self.FLAG.write(0xFF if val == 0 else 0x00, self.FLAG_Z)
        else:
            self.FLAG.write(0x00, self.FLAG_Z)
        self.FLAG.write(0x00, self.FLAG_H)
        self.FLAG.write(0x00, self.FLAG_N)

        self.PC.incr(2 if cb_op else 1)
        if cb_op:
            if from_memory:
                return 16
            else:
                return 8
        else:
            return 4

    def op_shift(self, dst, from_memory, left, arithmetic):
        val = dst.read()
        if from_memory:
            val = self.bus.read(val)

        drop_bit_idx = 7 if left else 0

        self.FLAG.write(0xFF if (val & (1 << drop_bit_idx)) != 0 else 0, self.FLAG_C)

        if left:
            val = val << 1
        else:
            val = val >> 1
            if arithmetic and (val & 0x40) != 0:
                    val |= 0x80
        val &= 0xFF

        if from_memory:
            self.bus.write(dst.read(), val)
        else:
            dst.write(val)

        self.FLAG.write(0x00, self.FLAG_H)
        self.FLAG.write(0x00, self.FLAG_N)
        self.FLAG.write(0xFF if val == 0 else 0x00, self.FLAG_Z)

        self.PC.incr(2)
        return 16 if from_memory else 8

    def op_swap(self, dst, from_memory):
        val = dst.read()
        if from_memory:
            val = self.bus.read(val)
        val = ((val & 0x0F) << 4) | (val >> 4)
        if from_memory:
            self.bus.write(dst.read(), val)
        else:
            dst.write(val)

        self.FLAG.write(0x00, self.FLAG_H)
        self.FLAG.write(0x00, self.FLAG_N)
        self.FLAG.write(0x00, self.FLAG_C)
        self.FLAG.write(0xFF if val == 0 else 0x00, self.FLAG_Z)

        self.PC.incr(2)
        return 16 if from_memory else 8

    def op_bit_test(self, idx, src, from_memory):
        val = src.read()
        if from_memory:
            val = self.bus.read(val)

        self.FLAG.write(0xFF, self.FLAG_H)
        self.FLAG.write(0x00, self.FLAG_N)
        self.FLAG.write(0xFF if (val & (1 << idx)) == 0 else 0x00, self.FLAG_Z)

        self.PC.incr(2)
        # TODO: is color matrix wrong? blargg expects 12
        # return 16 if from_memory else 8
        return 12 if from_memory else 8

    def op_bit_modify(self, idx, dst, reset, from_memory):
        if not from_memory:            
            dst.write(0x00 if reset else 0xFF, 1 << idx)
        else:
            val = self.bus.read(self.HL.read())
            if reset:
                val &= ~(1 << idx)
            else:
                val |= 1 << idx
            self.bus.write(self.HL.read(), val)

        self.PC.incr(2)
        return 16 if from_memory else 8

    def op_daa(self):
        # TODO: compare the commented out implementation with the in-use one,
        # which is more or less copied from http://forums.nesdev.com/viewtopic.php?t=9088
        # See if they end up producing the same results for all A

        # carry = False
        # if (self.FLAG.read() & self.FLAG_H) != 0 or (self.A.read() & 0x0F) > 0x09:
        #     carry, _ = self.A.flagged_incr(0x06)

        # if (self.FLAG.read() & self.FLAG_C) != 0 or (self.A.read() & 0xF0) > 0x90:
        #     new_carry, _ = self.A.flagged_incr(0x60)
        #     carry |= new_carry

        # self.FLAG.write(0x00, self.FLAG_H)
        # self.FLAG.write(0xFF if carry else 0x00, self.FLAG_C)
        # self.FLAG.write(0xFF if self.A.read() == 0 else 0x00, self.FLAG_Z)

        a = self.A.read()
        if (self.FLAG.read() & self.FLAG_N) == 0:
            if (self.FLAG.read() & self.FLAG_H) != 0 or (a & 0xF) > 9:
                a += 0x06
            if (self.FLAG.read() & self.FLAG_C) != 0 or a > 0x9F:
                a += 0x60
        else:        
            if (self.FLAG.read() & self.FLAG_H) != 0:
                a = (a-0x06) & 0xFF
            if (self.FLAG.read() & self.FLAG_C) != 0:
                a = (a-0x60) & 0x1FF
        
        self.FLAG.write(0x00, self.FLAG_H)
        FLAG = self.FLAG.read()
        FLAG |= self.FLAG_C if (a & 0x100) != 0 else 0x00
        self.FLAG.write(FLAG)
        a &= 0xFF
        self.FLAG.write(0xFF if a == 0 else 0x00, self.FLAG_Z)
        self.A.write(a)

        self.PC.incr(1)

        return 4

    def op_cpl(self):
        self.A.write(~self.A.read() & 0xFF)
        self.FLAG.write(self.FLAG.read() | self.FLAG_H | self.FLAG_N)
        self.PC.incr(1)
        return 4

    def op_scf(self):
        self.FLAG.write(self.FLAG.read() & ~self.FLAG_H & ~self.FLAG_N)
        self.FLAG.write(self.FLAG.read() | self.FLAG_C)
        self.PC.incr(1)
        return 4

    def op_ccf(self):
        self.FLAG.write(self.FLAG.read() & ~self.FLAG_H & ~self.FLAG_N)
        carry = (self.FLAG.read() & self.FLAG_C) != 0
        if carry:
            self.FLAG.write(self.FLAG.read() & ~self.FLAG_C)
        else:
            self.FLAG.write(self.FLAG.read() | self.FLAG_C)
        self.PC.incr(1)
        return 4

    def op_jp(self, addr_reg):
        self.PC.write(addr_reg.read())
        return 4

    def op_jp_imm(self, conditional_idx):
        if conditional_idx is None or self.cc[conditional_idx]():
            self.PC.write(self.bus.read_16(self.PC.read()+1))
            return 16
        else:
            self.PC.incr(3)
            return 12

    def op_jr(self):
        r8 = self.bus.read(self.PC.read()+1)
        if (r8 & 0x80) != 0:
            r8 |= 0xFF00
        self.PC.incr(2)
        self.PC.incr(r8)
        return 12

    def op_jr_condition(self, conditional_idx):
        if conditional_idx is None or self.cc[conditional_idx]():
            r8 = self.bus.read(self.PC.read()+1)
            if (r8 & 0x80) != 0:
                r8 |= 0xFF00
            self.PC.incr(2)
            self.PC.incr(r8)
            return 12
        else:
            self.PC.incr(2)
            return 8

    def op_ret(self, conditional_idx, enable_interrupts):
        if conditional_idx is None or self.cc[conditional_idx]():
            if enable_interrupts:
                self._IME = True
            self.PC.write(self.bus.read_16(self.SP.read()))
            self.SP.incr(2)
            # TODO: color matrix says unconditional ret is 16, pdf says 8
            # which is it???
            # nb: same deal with RETI
            return 16 if conditional_idx is None else 20
        else:
            self.PC.incr(1)
            return 8

    def op_call(self, conditional_idx):
        if conditional_idx is None or self.cc[conditional_idx]():
            self.SP.incr(-2)
            self.bus.write_16(self.SP.read(),self.PC.read()+3)

            self.PC.write(self.bus.read_16(self.PC.read()+1))
            return 24
        else:
            self.PC.incr(3)
            return 12

    def op_rst(self, new_pc):
        self.SP.incr(-2)
        self.bus.write_16(self.SP.read(),self.PC.read()+1)

        self.PC.write(new_pc)
        # TODO: is color matrix wrong? blargg expects 16
        # return 32
        return 16

    def op_change_interrupts_delayed(self, enabled):
        # TODO: how to do the delay part?
        self._IME = enabled
        self.PC.incr(1)
        return 4

    def op_halt(self):
        self._halted = True
        if self._IME:
            self.PC.incr(1)
        else:
            # TODO: make sure this is exactly right
            # see discussion on https://www.reddit.com/r/EmuDev/comments/5ie3k7/infinite_loop_trying_to_pass_blarggs_interrupt/
            self.PC.incr(2)
        return 4

    def op_stop(self):
        self._stopped = True
        self.PC.incr(2)
        return 4

    def op_add(self, operand, from_memory, with_carry, negative):
        long_op = False
        op_bytes = 1

        val = operand.read()
        if from_memory:
            val = self.bus.read(val)
            long_op = True

        if isinstance(operand, IMMEDIATE_REG):
            long_op = True
            op_bytes += 1

        (carry, half_carry) = self.A.flagged_incr(val if not negative else -val)

        if with_carry:
            if (self.FLAG.read() & self.FLAG_C) != 0:

                (second_carry, second_half_carry) = self.A.flagged_incr(1 if not negative else -1)

                carry |= second_carry
                half_carry |= second_half_carry

        self.FLAG.write(0xFF if carry else 0x00, self.FLAG_C)
        self.FLAG.write(0xFF if half_carry else 0x00, self.FLAG_H)
        self.FLAG.write(0xFF if self.A.read() == 0 else 0x00, self.FLAG_Z)
        self.FLAG.write(0xFF if negative else 0x00, self.FLAG_N)

        self.PC.incr(op_bytes)
        return 8 if long_op else 4

    def op_bitwise(self, operand, from_memory, operation):
        long_op = False
        op_bytes = 1

        val = operand.read()
        if from_memory:
            val = self.bus.read(val)
            long_op = True

        if isinstance(operand, IMMEDIATE_REG):
            long_op = True
            op_bytes += 1

        self.A.write(operation(self.A.read(), val))

        if operation == operator.and_:
            H_val = 0xFF
        else:
            H_val = 0x00

        self.FLAG.write(0xFF if self.A.read() == 0 else 0x00, self.FLAG_Z)
        self.FLAG.write(0x00, self.FLAG_N)
        self.FLAG.write(H_val, self.FLAG_H)
        self.FLAG.write(0x00, self.FLAG_C)

        self.PC.incr(op_bytes)
        return 8 if long_op else 4

    def op_compare(self, operand, from_memory):
        # NB: if we ever code interrupts based on register modification, this
        # may cause false positives
        old_a = self.A.read()
        cycles = self.op_add(operand, from_memory, False, True)
        self.A.write(old_a)
        return cycles

    def decode(self, opcode):
        # based on http://www.z80.info/decoding.htm
        #
        # an opcode table would probably be faster, but this is more fun
        x = (opcode & 0b11000000) >> 6
        y = (opcode & 0b00111000) >> 3
        z = (opcode & 0b00000111) >> 0
        p = (opcode & 0b00110000) >> 4
        q = (opcode & 0b00001000) >> 3

        if x == 0:
            if z == 0:
                if y == 0:
                    return self.op_nop()
                elif y == 1:
                    return self.op_mem_store_sp()
                elif y == 2:
                    return self.op_stop()
                elif y == 3:
                    return self.op_jr()
                elif 4 <= y <= 7:
                    return self.op_jr_condition(y-4)
            elif z == 1:
                if q == 0:
                    return self.op_ld_imm_16(self.rp[p])
                elif q == 1:
                    return self.op_add_16(self.HL, self.rp[p])
            elif z == 2:
                if q == 0:
                    if p == 0:
                        return self.op_mem_store_indirect(self.BC, self.A)
                    elif p == 1:
                        return self.op_mem_store_indirect(self.DE, self.A)
                    elif p == 2:
                        return self.op_mem_store_indirect(self.HL, self.A, 1)
                    elif p == 3:
                        return self.op_mem_store_indirect(self.HL, self.A, -1)
                elif q == 1:
                    if p == 0:
                        return self.op_mem_load_indirect(self.BC, self.A)
                    elif p == 1:
                        return self.op_mem_load_indirect(self.DE, self.A)
                    elif p == 2:
                        return self.op_mem_load_indirect(self.HL, self.A, 1)
                    elif p == 3:
                        return self.op_mem_load_indirect(self.HL, self.A, -1)
            elif z == 3:
                if q == 0:
                        return self.op_inc_16(self.rp[p], 1)
                elif q == 1:
                        return self.op_inc_16(self.rp[p], -1)
            elif z == 4:
                if y == 6:
                    return self.op_mem_inc_8(self.HL, 1)
                else:
                    return self.op_inc_8(self.r[y], 1)
            elif z == 5:
                if y == 6:
                    return self.op_mem_inc_8(self.HL, -1)
                else:
                    return self.op_inc_8(self.r[y], -1)
            elif z == 6:
                if y == 6:
                    return self.op_mem_store_indirect_imm(self.HL)
                else:
                    return self.op_ld_imm_8(self.r[y])
            elif z == 7:
                if y == 0:
                    return self.op_rot(self.A, False, True, False)
                elif y == 1:
                    return self.op_rot(self.A, False, False, False)
                elif y == 2:
                    return self.op_rot(self.A, False, True, True)
                elif y == 3:
                    return self.op_rot(self.A, False, False, True)
                elif y == 4:
                    return self.op_daa()
                elif y == 5:
                    return self.op_cpl()
                elif y == 6:
                    return self.op_scf()
                elif y == 7:
                    return self.op_ccf()
        elif x == 1:
            if z == 6 and y == 6:
                return self.op_halt()
            elif z == 6:
                return self.op_mem_load_indirect(self.HL, self.r[y])
            elif y == 6:
                return self.op_mem_store_indirect(self.HL, self.r[z])
            else:
                return self.op_ld(self.r[y], self.r[z])
        elif x == 2:
            if z == 6:
                return self.alu[y](self.HL, True)
            else:
                return self.alu[y](self.r[z], False)
        elif x == 3:
            if z == 0:
                if y <= 3:
                    return self.op_ret(y, False)
                elif y == 4:
                    return self.op_mem_store(self.IMMEDIATE_8, self.A, 0xFF00)
                elif y == 5:
                    return self.op_add_sp(self.SP, True)
                elif y == 6:
                    return self.op_mem_load(self.A, 0xFF00)
                elif y == 7:
                    return self.op_add_sp(self.HL, False)
            elif z == 1:
                if q == 0:
                    return self.op_mem_pop(self.rp2[p])
                elif q == 1:
                    if p == 0:
                        return self.op_ret(None, False)
                    elif p == 1:
                        return self.op_ret(None, True)
                    elif p == 2:
                        return self.op_jp(self.HL)
                    elif p == 3:
                        return self.op_ld(self.SP, self.HL)
            elif z == 2:
                if y <= 3:
                    return self.op_jp_imm(y)
                elif y == 4:
                    # TODO: color matrix says this is a 2 byte intsr, not sure
                    # whether to trust that or not
                    return self.op_mem_store_indirect(self.C, self.A, 0, 0xFF00)
                elif y == 5:
                    return self.op_mem_store(self.IMMEDIATE_16, self.A)
                elif y == 6:
                    # TODO: color matrix says this is a 2 byte intsr, not sure
                    # whether to trust that or not
                    return self.op_mem_load_indirect(self.C, self.A, 0, 0xFF00)
                elif y == 7:
                    return self.op_mem_load(self.A)
            elif z == 3:
                if y == 0:
                    return self.op_jp_imm(None)
                elif y == 1:
                    return self.cb_decode(self.bus.read(self.PC.read()+1))
                elif 2 <= y <= 5:
                    pass
                elif y == 6:
                    return self.op_change_interrupts_delayed(False)
                elif y == 7:
                    return self.op_change_interrupts_delayed(True)
            elif z == 4:
                if y <= 3:
                    return self.op_call(y)
                else:
                    pass
            elif z == 5:
                if q == 0:
                    return self.op_mem_push(self.rp2[p])
                elif q == 1:
                    if p == 0:
                        return self.op_call(None)
                    else:
                        pass
            elif z == 6:
                return self.alu[y](self.IMMEDIATE_8, False)
            elif z == 7:
                return self.op_rst(y*8)

        raise CPUOpcodeException(opcode)

    def cb_decode(self, opcode):
        x = (opcode & 0b11000000) >> 6
        y = (opcode & 0b00111000) >> 3
        z = (opcode & 0b00000111) >> 0

        from_memory = z == 6
        dst_reg = self.HL if from_memory else self.r[z]
        if x == 0:
            return self.rot[y](dst_reg, from_memory)
        elif x == 1:
            return self.op_bit_test(y, dst_reg, from_memory)
        elif x == 2:
            return self.op_bit_modify(y, dst_reg, True, from_memory)
        elif x == 3:
            return self.op_bit_modify(y, dst_reg, False, from_memory)

        raise CPUOpcodeException(opcode)

    def core_dump(self):
        out = []
        # TODO: make sure these bus/reg reads don't have side effects
        op = self.bus.read(self.PC.read())
        if op == 0xCB:
            op = "0xCB%02X" % self.bus.read(self.PC.read()+1)
            imm_offset = 2
        else:
            op = "0x%02X" % op
            imm_offset = 1
        out.append("PC\t0x%04X = %s" % (self.PC.read(), op))
        out.append("imm\t0x%04X" % self.bus.read_16(self.PC.read()+imm_offset))
        out.append("SP\t0x%04X" % self.SP.read())
        out.append("BC\t0x%04X" % self.BC.read())
        out.append("DE\t0x%04X" % self.DE.read())
        out.append("HL\t0x%04X" % self.HL.read())
        out.append("AF\t0x%04X" % self.AF.read())
        if self.F.read() & self.FLAG_Z:
            out[-1] += " Z"
        if self.F.read() & self.FLAG_N:
            out[-1] += " N"
        if self.F.read() & self.FLAG_H:
            out[-1] += " H"
        if self.F.read() & self.FLAG_C:
            out[-1] += " C"
        return "\n".join(out)

    def service_interrupts(self):
        # TODO: pull out magic numbers
        # TODO: investigate hardware behavior if IF bits 5-7
        # are set (undefined interrupts :o ??)
        if self._IME or self._halted:
            IE = self.bus.read(0xFFFF)
            IF = self.bus.read(0xFF0F)
            interrupts = IE & IF
            if interrupts != 0:
                for idx in xrange(8):
                    interrupt_mask = 1 << idx
                    if (interrupts & interrupt_mask) != 0:
                        # Make sure to un-halt the CPU
                        self._halted = False
                        self._stopped = False

                        if self._IME:
                            # Clear serviced IRQ and disable interrupts
                            self.bus.write(0xFF0F, IF & ~interrupt_mask)
                            self._IME = False

                            # Push PC onto stack
                            self.SP.incr(-2)
                            self.bus.write_16(self.SP.read(),self.PC.read())

                            # Jump to handler!
                            self.PC.write(0x40 + 8*idx)
                            return 5
                        else:
                            # TODO: figure out what this value should actually
                            # be (maybe read TCAGBD more?)
                            return 0
            return 0
        else:
            return 0

