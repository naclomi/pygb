import debug
import bus

class ROM(bus.BUS_OBJECT):
    def __init__(self, rom_bin):
        self.rom_bytes = []
        rom_bin.seek(0x00)
        try:
            while True:
                self.rom_bytes.append(ord(rom_bin.read(1)))
        except:
            pass
        self.rom_bytes = tuple(self.rom_bytes)

    def slice(self, addr_lo, addr_hi):
        return self.rom_bytes[addr_lo:addr_hi+1]

    def bus_read(self, addr):
        return self.rom_bytes[addr]

    def bus_write(self, addr, value):
        print "WARNING: Write to ROM address 0x%04X=%02X" % (addr, value)

class RAM(bus.BUS_OBJECT):
    def __init__(self, size=2**16):
        super(RAM, self).__init__()
        self.ram_bytes = [0x00]*size

    def bus_read(self, addr):
        if addr < len(self.ram_bytes):
            return self.ram_bytes[addr]
        else:
            print "WARNING: Read from out-of-bounds RAM address %04X" % (addr)
            return 0xFF

    def bus_write(self, addr, value):
        if addr < len(self.ram_bytes):
            self.ram_bytes[addr] = value
        else:
            print "WARNING: Write to out-of-bounds RAM address %04X=%02X" % (addr, value)


class MEM_SEGMENT(bus.BUS_OBJECT):
    def __init__(self, segment_idx, mbc):
        super(MEM_SEGMENT, self).__init__()
        self.segment_idx = segment_idx
        self.mbc = mbc

    def bus_write(self, addr, value):
        self.mbc.write(self.segment_idx, addr, value)

    def bus_read(self, addr):
        return self.mbc.read(self.segment_idx, addr)


class MBC(object):
    def __init__(self, rom, ram):
        self.rom = rom
        self.ram = ram


class MBC_NONE(MBC):
    def write(self, segment, addr, value):
        if segment == 0:
            self.rom.bus_write(addr, value)
        elif segment == 1:
            self.rom.bus_write(0x4000+addr, value)
        elif segment == 2:
            self.ram.bus_write(addr, value)

    def read(self, segment, addr):
        if segment == 0:
            return self.rom.bus_read(addr)
        elif segment == 1:
            return self.rom.bus_read(0x4000+addr)
        elif segment == 2:
            return self.ram.bus_read(addr)

class MBC1(MBC):
    def __init__(self, rom, ram):
        super(MBC1, self).__init__(rom, ram)
        self.rom_bank = 1
        self.ram_bank = 0
        self.ram_enable = 0
        self.rom_ram_mode = 0

    def write(self, segment, addr, value):
        if segment == 0:
            if addr <= 0x1FFF:
                # TODO: should disabling RAM reset its values? should it
                # reset its bank?
                self.ram_enable = (value & 0x0F) == 0x0A
            elif addr <= 0x3FFF:
                value = value & 0x1F
                if value == 0:
                    value += 1
                self.rom_bank &= 0x60
                self.rom_bank |= value
            else:
                raise Exception("Unknown MBC operation")
        elif segment == 1:
            if addr <= 0x1FFF:
                value = value & 0x03
                if self.rom_ram_mode == 0:
                    self.rom_bank |= value << 5
                else:
                    self.ram_bank = value
            elif addr <= 0x3FFF:
                self.rom_ram_mode = value != 0
                if self.rom_ram_mode == 0:
                    self.ram_bank = 0
                else:
                    self.rom_bank &= 0x1F
            else:
                raise Exception("Unknown MBC operation")
        elif segment == 2:
            if self.ram_enable:
                self.ram.bus_write(self.ram_bank*0x2000+addr, value)

    def read(self, segment, addr):
        if segment == 0:
            return self.rom.bus_read(addr)
        elif segment == 1:
            return self.rom.bus_read(self.rom_bank*0x4000+addr)
        elif segment == 2:
            if self.ram_enable:
                return self.ram.bus_read(self.ram_bank*0x2000+addr)
            else:
                return 0xFF

class MBC2(MBC):
    def __init__(self, rom, ram):
        super(MBC2, self).__init__(rom, ram)
        self.rom_bank = 1
        self.ram_enable = 0
        # TODO: do we need to force-create a 512b ram for this MBC?

    def write(self, segment, addr, value):
        if segment == 0:
            if addr <= 0x1FFF:
                # TODO: should disabling RAM reset its values? should it
                # reset its bank?
                if (addr & 0x0100) == 0:
                    self.ram_enable = (value & 0x0F) == 0x0A
            elif addr <= 0x3FFF:
                self.rom_bank = value & 0x0F
            else:
                raise Exception("Unknown MBC operation")
        else:
            raise Exception("Unknown MBC operation")

    def read(self, segment, addr):
        if segment == 0:
            return self.rom.bus_read(addr)
        elif segment == 1:
            return self.rom.bus_read(self.rom_bank*0x4000+addr)
        elif segment == 2:
            if self.ram_enable:
                return self.ram.bus_read(addr)
            else:
                return 0xFF

class MBC3(MBC):
    def __init__(self, rom, ram):
        raise Exception("%s is unimplemented" % type(self).__name__)

class MBC4(MBC):
    def __init__(self, rom, ram):
        raise Exception("%s is unimplemented" % type(self).__name__)

class MBC5(MBC):
    def __init__(self, rom, ram):
        raise Exception("%s is unimplemented" % type(self).__name__)

class MBC6(MBC):
    def __init__(self, rom, ram):
        raise Exception("%s is unimplemented" % type(self).__name__)

class MBC7(MBC):
    def __init__(self, rom, ram):
        raise Exception("%s is unimplemented" % type(self).__name__)

class MMM01(MBC):
    def __init__(self, rom, ram):
        raise Exception("%s is unimplemented" % type(self).__name__)

class CAMERA(MBC):
    def __init__(self, rom, ram):
        raise Exception("%s is unimplemented" % type(self).__name__)

class TAMA5(MBC):
    def __init__(self, rom, ram):
        raise Exception("%s is unimplemented" % type(self).__name__)

class HuC3(MBC):
    def __init__(self, rom, ram):
        raise Exception("%s is unimplemented" % type(self).__name__)

class HuC1(MBC):
    def __init__(self, rom, ram):
        raise Exception("%s is unimplemented" % type(self).__name__)


class CARTRIDGE(object):
    def __init__(self, bus, rom_bin):
        self.bus = bus
        self.rom = ROM(rom_bin)

        self.filename = rom_bin.name

        self.cartridge_type = self.rom.bus_read(0x147)
        self.rom_size = (1024*32) << self.rom.bus_read(0x148)
        self.ram_size = [0, 1024*2, 1024*8, 1024*32, 1024*128, 1024*64][self.rom.bus_read(0x149)]
        self.title = "".join(map(chr, self.rom.slice(0x134, 0x143)))

        self.mbc_type = {
            0x00: MBC_NONE,
            0x01: MBC1,
            0x02: MBC1,
            0x03: MBC1,
            0x05: MBC2,
            0x06: MBC2,
            0x08: MBC_NONE,
            0x09: MBC_NONE,
            0x0B: MMM01,
            0x0C: MMM01,
            0x0D: MMM01,
            0x0F: MBC3,
            0x10: MBC3,
            0x11: MBC3,
            0x12: MBC3,
            0x13: MBC3,
            0x19: MBC5,
            0x1A: MBC5,
            0x1B: MBC5,
            0x1C: MBC5,
            0x1D: MBC5,
            0x1E: MBC5,
            0x20: MBC6,
            0x22: MBC7,
            0xFC: CAMERA,
            0xFD: TAMA5,
            0xFE: HuC3,
            0xFF: HuC1,
        }[self.cartridge_type]

        self.ram_present = self.cartridge_type in {
            0x02,
            0x03,
            0x06,
            0x08,
            0x09,
            0x0C,
            0x0D,
            0x10,
            0x12,
            0x13,
            0x1A,
            0x1B,
            0x1D,
            0x1E,
            0x20,
            0x22,
            0xFF,
        }
        self.ram_battery = self.cartridge_type in {
            0x03,
            0x06,
            0x09,
            0x0D,
            0x0F,
            0x10,
            0x13,
            0x1B,
            0x1E,
            0x20,
            0x22,
            0xFF,
        }
        self.timer_present = self.cartridge_type in {
            0x0F,
            0x10,
        }
        self.rumble_present = self.cartridge_type in {
            0x1C,
            0x1D,
            0x1E,
        }
        self.accel_present = self.cartridge_type in {
            0x22,
        }

        self.ram = RAM(self.ram_size if self.ram_present else 0)
        self.mbc = self.mbc_type(self.rom, self.ram)
        # TODO: move the accessory flags (timer, rumble, accel) into mbc
        # implementations somehow
        # TODO: implement battery saves :) !!

        self.rom_0 = MEM_SEGMENT(0, self.mbc)
        self.bus.attach(self.rom_0, 0x0000, 0x3FFF)
        self.rom_N = MEM_SEGMENT(1, self.mbc)
        self.bus.attach(self.rom_N, 0x4000, 0x7FFF)
        self.ram_N = MEM_SEGMENT(2, self.mbc)
        self.bus.attach(self.ram_N, 0xA000, 0xBFFF)

    def allow_bus_access(self, en):
        # TODO: not sure what pars of cart should be disabled during DMA
        # blockade, opus5 breaks if ROM is included
        # self.rom_0.bus_enabled = en
        # self.rom_N.bus_enabled = en
        self.ram_N.bus_enabled = en
