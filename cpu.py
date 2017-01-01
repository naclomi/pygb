import operator
import bus

class REG(bus.BUS_OBJECT):
    def __init__(self, name, size=8, init=0):
        super(REG, self).__init__()
        self.name = name
        self.size = size
        self.value = init
        self.mask = 2**size-1
        self.half_mask = 2**(size/2)-1

    def read(self):
        return self.value

    def write(self, value, mask=None):
        value &= self.mask
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
        carry = False
        half_carry = False
        
        half_sum = (self.value & self.half_mask) + (delta & self.half_mask)
        if (half_sum & ~self.half_mask) != 0:
            half_carry = True

        self.value += delta
        if (self.value & ~self.mask) != 0:
            carry = True
        self.value &= self.mask

        if delta < 0:
            # If this was a decr operation, change the carries into borrows
            carry = not carry
            half_carry = not half_carry

        return (carry, half_carry)

class FUSED_REG(object):
    def __init__(self, reg_hi, reg_lo):
        self.name = reg_hi.name + reg_lo.name
        self.size = reg_hi.size + reg_lo.size

        self.reg_hi = reg_hi
        self.reg_lo = reg_lo

    def read(self):
        return self.reg_hi.read() << self.reg_hi.size | self.reg_lo.read()

    def write(self, value, mask = None):
        if mask is None:
            lo_mask = hi_mask = None
        else:
            lo_mask = mask & self.reg_lo.mask
            hi_mask = (mask >> self.reg_lo.size) & self.reg_hi.mask
        self.reg_lo.write(value & self.reg_lo.mask, lo_mask)
        value = value >> self.reg_lo.size
        self.reg_hi.write(value & self.reg_hi.mask, hi_mask)

    def incr(self, delta):
        lo_delta = delta & self.reg_lo.mask
        carry, _ = self.reg_lo.incr(lo_delta)
        
        hi_delta = (delta >> self.reg_lo.size)
        if carry:
            hi_delta += 1 if delta > 0 else -1
        carry, half_carry = self.reg_hi.incr(hi_delta)

        return (carry, half_carry)


class IMMEDIATE_REG(object):
    def __init__(self, cpu, size=8):
        if size != 8 and size != 16:
            raise Exception("Bad size")
        self.cpu = cpu
        self.name = "IMMEDIATE_%d" % size
        self.size = size

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
        self.T_cyc = 1 / self.f

        # TODO: fill in initial values for everything (see The PDF pg18)
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

        self.FLAG = REG("FLAG")
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
            # TODO: Double check for any differences between CB RLC A and RLC A
            lambda dst, from_memory: self.op_rot(dst, from_memory, True, True, True), # RLC
            lambda dst, from_memory: self.op_rot(dst, from_memory, False, True, True), # RRC
            lambda dst, from_memory: self.op_rot(dst, from_memory, True, False, True), # RL
            lambda dst, from_memory: self.op_rot(dst, from_memory, False, False, True), # RR
            lambda dst, from_memory: self.op_shift(dst, from_memory, True, True), # SLA
            lambda dst, from_memory: self.op_shift(dst, from_memory, False, True), # SRA
            self.op_swap,
            lambda dst, from_memory: self.op_shift(dst, from_memory, False, False), # SRL
        ]

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

    def op_mem_store(self, src, addr_offset=0):
        addr = self.bus.read_16(self.PC.read()+1)
        addr += addr_offset
        addr &= 0xFFFF
        self.bus.write(addr, src.read())
        self.PC.incr(3)
        return 12 if src is not self.A else 16

    def op_mem_store_sp(self):
        self.bus.write_16(self.bus.read_16(self.PC.read()), self.SP.read())
        self.PC.incr(3)
        return 20

    def op_mem_store_indirect_imm(self, addr_reg):
        self.bus.write(addr_reg.read(), self.bus.read(self.PC.read()+1))
        self.PC.incr(2)
        return 12

    def op_mem_load(self, dst, addr_offset=0):
        addr = self.bus.read_16(self.PC.read()+1)
        addr += addr_offset
        addr &= 0xFFFF
        dst.write(self.bus.read(addr))
        self.PC.incr(3)
        return 12 if src is not self.A else 16

    def op_mem_pop(self, dst):
        dst.write(self.bus.read_16(self.SP.read()))
        self.SP.incr(2)
        self.PC.incr(1)
        # TODO: the colorful gb opcode matrix indicates that POP AF affects all
        # flags Z N H C while none of the others do. This seems like its a typo,
        # but double-check
        return 12

    def op_mem_push(self, src):
        self.SP.incr(-2)
        self.bus.write_16(self.SP.read(), src.read())
        self.PC.incr(1)
        return 116

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
        (carry, half_carry) = dst.incr(src.read())

        self.FLAG.write(0, self.FLAG_N)
        self.FLAG.write(0xFF if half_carry else 0x00, self.FLAG_H)
        self.FLAG.write(0xFF if carry else 0x00, self.FLAG_C)

        self.PC.incr(1)
        return 8

    def op_ldhl_sp_imm(self):
        # TODO: figure out if this is the right way to sign extend, and where to
        # do it:
        r8 = self.bus.read(self.PC.read()+1)
        if (r8 & 0x80) != 0:
            r8 |= 0xFF00
        self.HL.write(r8)
        self.op_add_16(self.HL, self.sp)
        # We want to increment by 2, but op_add_16 above already incremented
        # the PC by 1
        self.PC.incr(1)
        return 12

    def op_add_sp(self):
        # TODO: figure out if this is the right way to sign extend, and where to
        # do it:
        r8 = self.bus.read(self.PC.read()+1)
        if (r8 & 0x80) != 0:
            r8 |= 0xFF00
        (carry, half_carry) = self.SP.incr(r8)

        self.FLAG.write(0x00, self.FLAG_Z)
        self.FLAG.write(0x00, self.FLAG_N)
        self.FLAG.write(0xFF if half_carry else 0x00, self.FLAG_H)
        self.FLAG.write(0xFF if carry else 0x00, self.FLAG_C)

        self.PC.incr(2)
        return 16

    def op_inc_16(self, dst, delta):
        (carry, half_carry) = dst.incr(delta)
        self.PC.incr(1)
        return 8

    def op_inc_8(self, dst, delta):
        (_, half_carry) = dst.incr(delta)

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

        carry = (SELF.FLAG.read() & self.FLAG_C) != 0
        val = carry << 8 | val

        rot_bit_idx = 8 if include_carry else 7
        if left:
            rot_bit = (val & (1 << rot_bit_idx)) != 0
            val = val << 1
            val |= rot_bit
        else:
            rot_bit = (val & 0x01) != 0
            val = val >> 1
            val |= rot_bit << rot_bit_idx
        val = val & 0xFF

        if from_memory:
            self.bus.write(dst.read(), val)
        else:
            dst.write(val)

        self.FLAG.write(0xFF if (val & (1 << rot_bit_idx)) != 0 else 0x00, self.FLAG_C)
        self.FLAG.write(0x00, self.FLAG_H)
        self.FLAG.write(0x00, self.FLAG_N)

        # TODO: double-check this FLAG_Z behavior, CB instructions actually
        # set Z appropriately while the color matrix says non-CB RLA/RLCA
        # 0's it out. Not sure which is the true behavior:
        self.FLAG.write(0xFF if val == 0 else 0x00, self.FLAG_Z)

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
        return 16 if from_memory else 8

    def op_bit_modify(self, idx, dst, reset, from_memory):
        if from_memory:            
            dst.write(0x00 if reset else 0xFF, 1 << idx)
        else:
            val = self.bus.read(dst.read())
            if reset:
                val &= ~(1 << idx)
            else:
                val |= 1 << idx
            self.bus.write(dst.read(), val)

        self.PC.incr(2)
        return 16 if from_memory else 8

    def op_daa(self):
        carry = False

        if (self.FLAG.read() & self.FLAG_H) != 0 or (self.A.read() & 0x0F) > 0x09:
            carry, _ = self.A.inc(0x06)

        if (self.FLAG.read() & self.FLAG_C) != 0 or (self.A.read() & 0xF0) > 0x90:
            new_carry, _ = self.A.inc(0x60)
            carry |= new_carry

        self.FLAG.write(0x00, self.FLAG_H)
        self.FLAG.write(0xFF if carry else 0x00, self.FLAG_C)
        self.FLAG.write(0xFF if self.A.read() == 0 else 0x00, self.FLAG_Z)

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
        # TODO: figure out if this is the right way to sign extend, and where to
        # do it:
        r8 = self.bus.read(self.PC.read()+1)
        if (r8 & 0x80) != 0:
            r8 |= 0xFF00
        self.PC.incr(2)
        self.PC.incr(r8)
        return 12

    def op_jr_condition(self, conditional_idx):
        if conditional_idx is None or self.cc[conditional_idx]():
            # TODO: figure out if this is the right way to sign extend, and where to
            # do it:
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
        self.bus.write_16(self.SP.read(),self.PC.read())

        self.PC.write(new_pc)
        return 32

    def op_change_interrupts_delayed(self, enabled):
        # TODO: how to do the delay part?
        self._IME = enabled
        self.PC.incr(1)
        return 4

    def op_halt(self):
        if self._IME:
            self._halted = True
            self.PC.incr(1)
        else:
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

        (carry, half_carry) = self.A.incr(val if not negative else -val)

        if with_carry:
            if (self.FLAG.read() & self.FLAG_C) != 0:
                (second_carry, second_half_carry) = self.A.incr(1 if not negative else -1)
                # TODO: not sure if this is correct behavior:
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

        self.FLAG.write(0xFF if self.A.read() == 0 else 0x00, self.FLAG_Z)
        self.FLAG.write(0x00, self.FLAG_N)
        self.FLAG.write(0xFF, self.FLAG_H)
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
                    return self.op_nop
                elif y == 1:
                    return self.op_mem_store_sp
                elif y == 2:
                    return self.op_stop
                elif y == 3:
                    return self.op_jr
                elif 4 <= y <= 7:
                    return lambda: self.op_jr_condition(y-4)
            elif z == 1:
                if q == 0:
                    return lambda: self.op_ld_imm_16(self.rp[p])
                elif q == 1:
                    return lambda: self.op_add_16(self.HL, self.rp[p])
            elif z == 2:
                if q == 0:
                    if p == 0:
                        return lambda: self.op_mem_store_indirect(self.BC, self.A)
                    elif p == 1:
                        return lambda: self.op_mem_store_indirect(self.DE, self.A)
                    elif p == 2:
                        return lambda: self.op_mem_store_indirect(self.HL, self.A, 1)
                    elif p == 3:
                        return lambda: self.op_mem_store_indirect(self.HL, self.A, -1)
                elif q == 1:
                    if p == 0:
                        return lambda: self.op_mem_load_indirect(self.BC, self.A)
                    elif p == 1:
                        return lambda: self.op_mem_load_indirect(self.DE, self.A)
                    elif p == 2:
                        return lambda: self.op_mem_load_indirect(self.HL, self.A, 1)
                    elif p == 3:
                        return lambda: self.op_mem_load_indirect(self.HL, self.A, -1)
            elif z == 3:
                if q == 0:
                        return lambda: self.op_inc_16(self.rp[p], 1)
                elif q == 1:
                        return lambda: self.op_inc_16(self.rp[p], -1)
            elif z == 4:
                if y == 6:
                    return lambda: self.op_mem_inc_8(self.HL, 1)
                else:
                    return lambda: self.op_inc_8(self.r[y], 1)
            elif z == 5:
                if y == 6:
                    return lambda: self.op_mem_inc_8(self.HL, -1)
                else:
                    return lambda: self.op_inc_8(self.r[y], -1)
            elif z == 6:
                if y == 6:
                    return lambda: self.op_mem_store_indirect_imm(self.HL)
                else:
                    return lambda: self.op_ld_imm_8(self.r[y])
            elif z == 7:
                if y == 0:
                    return lambda: self.op_rot(self.A, False, True, True)
                elif y == 1:
                    return lambda: self.op_rot(self.A, False, False, True)
                elif y == 2:
                    return lambda: self.op_rot(self.A, False, True, False)
                elif y == 3:
                    return lambda: self.op_rot(self.A, False, False, False)
                elif y == 4:
                    return self.op_daa
                elif y == 5:
                    return self.op_cpl
                elif y == 6:
                    return self.op_scf
                elif y == 7:
                    return self.op_ccf
        elif x == 1:
            if z == 6 and y == 6:
                return self.op_halt
            elif z == 6:
                return lambda: self.op_mem_load_indirect(self.HL, self.r[y])
            elif y == 6:
                return lambda: self.op_mem_store_indirect(self.HL, self.r[z])
            else:
                return lambda: self.op_ld(self.r[y], self.r[z])
        elif x == 2:
            if z == 6:
                return lambda: self.alu[y](self.HL, True)
            else:
                return lambda: self.alu[y](self.r[z], False)
        elif x == 3:
            if z == 0:
                if y <= 3:
                    return lambda: self.op_ret(y, False)
                elif y == 4:
                    return lambda: self.op_mem_store(self.A, 0xFF00)
                elif y == 5:
                    return self.op_add_sp
                elif y == 6:
                    return lambda: self.op_mem_load(self.A, 0xFF00)
                elif y == 7:
                    return self.op_ldhl_sp_imm
            elif z == 1:
                if q == 0:
                    return lambda: self.op_mem_pop(self.rp2[p])
                elif q == 1:
                    if p == 0:
                        return lambda: self.op_ret(None, False)
                    elif p == 1:
                        return lambda: self.op_ret(None, True)
                    elif p == 2:
                        return lambda: self.op_jp(self.HL)
                    elif p == 3:
                        return lambda: self.op_ld(self.SP, self.HL)
            elif z == 2:
                if y <= 3:
                    return lambda: self.op_jp_imm(y)
                elif y == 4:
                    # TODO: color matrix says this is a 2 byte intsr, not sure
                    # whether to trust that or not
                    return lambda: self.op_mem_store_indirect(self.C, self.A, 0, 0xFF00)
                elif y == 5:
                    return lambda: self.op_mem_store(self.A)
                elif y == 6:
                    # TODO: color matrix says this is a 2 byte intsr, not sure
                    # whether to trust that or not
                    return lambda: self.op_mem_load_indirect(self.C, self.A, 0, 0xFF00)
                elif y == 7:
                    return lambda: self.op_mem_load(self.A)
            elif z == 3:
                if y == 0:
                    return lambda: self.op_jp_imm(None)
                elif y == 1:
                    return self.cb_decode(self.bus.read(self.PC.read()+1))
                elif 2 <= y <= 5:
                    pass
                elif y == 6:
                    return lambda: self.op_change_interrupts_delayed(False)
                elif y == 7:
                    return lambda: self.op_change_interrupts_delayed(True)
            elif z == 4:
                if y <= 3:
                    return lambda: self.op_call(y)
                else:
                    pass
            elif z == 5:
                if q == 0:
                    return lambda: self.op_mem_push(self.rp2[p])
                elif q == 1:
                    if p == 0:
                        return lambda: self.op_call(None)
                    else:
                        pass
            elif z == 6:
                return lambda: self.alu[y](self.IMMEDIATE_8, False)
            elif z == 7:
                return lambda: self.op_rst(y*8)

        raise CPUOpcodeException(opcode)

    def cb_decode(self, opcode):
        x = (opcode & 0b11000000) >> 6
        y = (opcode & 0b00111000) >> 3
        z = (opcode & 0b00000111) >> 0

        from_memory = z == 6
        if x == 0:
            return lambda: self.rot[y](self.r[z], from_memory)
        elif x == 1:
            return lambda: self.op_bit_test(y, self.r[z], from_memory)
        elif x == 2:
            return lambda: self.op_bit_modify(y, self.r[z], True, from_memory)
        elif x == 3:
            return lambda: self.op_bit_modify(y, self.r[z], False, from_memory)

        raise CPUOpcodeException(opcode)

    def service_interrupts(self):
        # TODO: pull out magic numbers
        # TODO: investigate hardware behavior if IF bits 5-7
        # are set (undefined interrupts :o ??)
        if self._IME:
            IE = self.bus.read(0xFFFF)
            IF = self.bus.read(0xFF0F)
            interrupts = IE & IF
            if interrupts != 0:
                for idx in xrange(8):
                    interrupt_mask = 1 << idx
                    if (interrupts & interrupt_mask) != 0:
                        # Clear serviced IRQ and disable interrupts
                        self.bus.write(0xFF0F, IF & ~interrupt_mask)
                        self._IME = False

                        # Push PC onto stack
                        self.SP.incr(-2)
                        self.bus.write_16(self.SP.read(),self.PC.read())

                        # Jump to handler!
                        self.PC.write(0x40 + 8*idx)
                        return 5
            return 0
        else:
            return 0

