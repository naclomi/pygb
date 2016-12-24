#!/usr/bin/python
import opcodes

class ROM(object):
    def __init__(self, rom_bin):
        rom_bytes = []
        if type(rom_bin) is file:
            rom_bin.seek(0x5D)
            rom_len = reduce(lambda x, y: x<<8 | y, map(ord, rom_bin.read(4)))
            print rom_len

            rom_bin.seek(0x61)
            try:
                while len(rom_bytes)<rom_len:
                    rom_bytes.append(ord(rom_bin.read(1)))
            except:
                pass
        print map(hex, rom_bytes)

class RAM(object):
    def __init__(self, size=2**16):
        self.values = [0x00]*size

class REG(object):
    def __init__(self, name, size=8, init=0):
        self.name = name
        self.size = size
        self.value = init
        self.mask = 2**size-1

    def get(self):
        return self.value

    def set(self, value)
        self.value = value & self.mask

class FUSED_REG(object):
    def __init__(self, reg_hi, reg_lo):
        self.name = reg_hi.name + reg_lo.name
        self.size = reg_hi.size + reg_lo.size

        self.reg_hi = reg_hi
        self.reg_lo = reg_lo

    def get(self):
        return self.reg_hi.get() << self.reg_hi.size | self.reg_lo.get()

    def set(self, value):
        self.reg_lo.set(value & self.reg_lo.mask)
        value = value >> self.reg_lo.size
        self.reg_hi.set(value & self.reg_hi.mask)

class CPU(object):
    def __init__(self, rom):
        self.regs = {}
        for reg in "ABCDEFHL":
            self.regs[reg] = REG(reg)
        self.regs["AF"] = FUSED_REG(self.regs["A"], self.regs["F"])
        self.regs["BC"] = FUSED_REG(self.regs["B"], self.regs["C"])
        self.regs["DE"] = FUSED_REG(self.regs["D"], self.regs["E"])
        self.regs["HL"] = FUSED_REG(self.regs["H"], self.regs["L"])

        self.regs["SP"] = REG("SP", 16, 0xFFFE)
        self.regs["PC"] = REG("PC", 16, 0x0100)

        self.regs["FLAG"] = REG("FLAG")

        self.ram = RAM()
        self.rom = rom

    def decode(self, instr):
        # based on http://www.z80.info/decoding.htm
        

    def read(self, addr):
        return self.rom[addr]




with open("tests/test.bin", "rb") as f:
    rom = ROM(f)
    cpu = CPU(rom)
    print "lol"