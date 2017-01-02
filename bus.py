
class BUS(object):
    def __init__(self):
        self.devices = []

    def attach(self, device, addr_lo, addr_hi):
        if not isinstance(device, BUS_OBJECT):
            raise TypeError()
        if device.bus is not None:
            raise Exception("Bus object already attached")

        device.bus_addr_lo = addr_lo
        device.bus_addr_hi = addr_hi
        self.devices.append(device)
        self.devices.sort(key=lambda d: d.bus_addr_lo)
        device.bus = self
        # TODO: ensure no overlap

    def read(self, addr):
        for device in self.devices:
            if device.bus_addr_lo <= addr <= device.bus_addr_hi:
                return device.bus_read(addr - device.bus_addr_lo)
        raise Exception("Read from HiZ address 0x%04lX" % addr)

    def write(self, addr, value):
        for device in self.devices:
            if device.bus_addr_lo <= addr <= device.bus_addr_hi:
                device.bus_write(addr - device.bus_addr_lo, value)
                return
        raise Exception("Write to HiZ address 0x%04lX" % addr)

    def read_16(self, addr):
        return self.read(addr) | (self.read(addr+1) << 8)

    def write_16(self, addr, value):
        self.write(addr, (value >> 0) & 0xFF)
        self.write(addr+1, (value >> 8) & 0xFF)


class BUS_OBJECT(object):
    def __init__(self):
        self.bus_addr_lo = None
        self.bus_addr_hi = None
        self.bus = None

    def bus_read(self, addr):
        raise Exception("Unimplemented method %s.bus_read" % str(type(self)))

    def bus_write(self, addr, value):
        raise Exception("Unimplemented method %s.bus_write" % str(type(self)))


