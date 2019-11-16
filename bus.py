
class BUS(object):
    def __init__(self):
        self.devices = []
        # TODO: remove profiling code:
        # self.reads = {}

        # Hard-code access to these because they're
        # read a LOT
        #
        # TODO: maybe should just redesign 
        # the BUS to be entirely hardcoded?
        self.ie_reg = None
        self.if_reg = None

    def attach(self, device, addr_lo, addr_hi):
        if not isinstance(device, BUS_OBJECT):
            raise TypeError()
        if device.bus is not None:
            raise Exception("Bus object already attached")

        if addr_lo == 0xffff:
            self.ie_reg = device
        if addr_lo == 0xff0f:
            self.if_reg = device

        device.bus_addr_lo = addr_lo
        device.bus_addr_hi = addr_hi
        self.devices.append((device, addr_lo, addr_hi))
        self.devices.sort(key=lambda d: d[0].bus_addr_lo)
        device.bus = self
        # TODO: ensure no overlap

    def read(self, addr, force=False):
        if addr == 0xffff:
            return self.ie_reg.bus_read(0)
        if addr == 0xff0f:
            return self.if_reg.bus_read(0)

        for device, addr_lo, addr_hi in self.devices:
            if addr_lo <= addr <= addr_hi:
                # TODO: remove profiling code:
                #self.reads[addr_lo] = self.reads.get(addr_lo, 0)+1
                if device.bus_enabled or force:
                    return device.bus_read(addr - addr_lo)
                else:
                    return 0xFF
        print("WARNING: Read from HiZ address 0x%04lX" % addr)
        return 0xFF

    def write(self, addr, value, force=False):
        for device, addr_lo, addr_hi in self.devices:
            if addr_lo <= addr <= addr_hi:
                if device.bus_enabled or force:
                    device.bus_write(addr - addr_lo, value)
                return
        print("WARNING: Write to HiZ address 0x%04lX" % addr)

    def read_16(self, addr):
        return self.read(addr) | (self.read(addr+1) << 8)

    def write_16(self, addr, value):
        self.write(addr, value & 0xFF)
        self.write(addr+1, value >> 8)


class BUS_OBJECT(object):
    def __init__(self):
        self.bus_addr_lo = None
        self.bus_addr_hi = None
        self.bus_enabled = True
        self.bus = None


    def bus_read(self, addr):
        raise Exception("Unimplemented method %s.bus_read" % str(type(self)))

    def bus_write(self, addr, value):
        raise Exception("Unimplemented method %s.bus_write" % str(type(self)))


