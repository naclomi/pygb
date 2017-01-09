#!/usr/bin/python
# TODO: rename everything leomulator
import sys

import pygame
import time
import video
import bus
import cpu

class ROM(bus.BUS_OBJECT):
    def __init__(self, rom_bin):
        super(ROM, self).__init__()
        self.rom_bytes = []
        if type(rom_bin) is file:
            rom_bin.seek(0x00)
            try:
                while True:
                    self.rom_bytes.append(ord(rom_bin.read(1)))
            except:
                pass

    def bus_read(self, addr):
        return self.rom_bytes[addr]


class RAM(bus.BUS_OBJECT):
    def __init__(self, size=2**16):
        super(RAM, self).__init__()
        self.ram_bytes = [0x00]*size

    def bus_read(self, addr):
        return self.ram_bytes[addr]

    def bus_write(self, addr, value):
        self.ram_bytes[addr] = value


class TIMER(bus.BUS_OBJECT):
    def __init__(self):
        super(TIMER, self).__init__()
        self.tick = 0.0
        self.clock = 0

        self.div_tick = 0.0
        self.div_clock = 0
        
        self.enabled = 0
        self.speed_select = 0
        
        self.frequencies = [4096,262144,65536,16384]
        self.periods = [1.0/f for f in self.frequencies]

        self.load_value = 0

        # ok why is the div register in the *middle* of the selectable
        # frequency spectrum? time to break out the PLL textbook...
        self.div_T = self.periods[3]

        # TODO: it would be fun to implement this with everything deriving from
        # one reference clock and all the obscure glitch behavior described by
        # the pandocs wiki

    def advance(self, delta):
        # Note that delta is **SIMULATED** time
        if self.enabled == 1:
            T = self.periods[self.speed_select]
            self.tick += delta
            if self.tick >= T:
                self.tick -= T
                self.clock += 1
                if self.clock > 255:
                    self.clock = self.load_value
                    # Trigger an interrupt
                    # TODO: pull these magic numbers out somewhere
                    IF_state = self.bus.read(0xFF0F)
                    IF_state |= 0x4
                    self.bus.write(0xFF0F, IF_state)

        self.div_tick += delta
        if self.div_tick >= self.div_T:
            self.div_tick -= self.div_T
            self.div_clock += 1
            self.div_clock &= 0xFF

    def bus_read(self, addr):
        if addr == 0: # DIV
            return self.div_clock
        elif addr == 1: # TIMA
            return self.clock
        elif addr == 2: # TMA
            return self.load_value
        elif addr == 3: # TAC
            val = self.enabled << 2
            val |= self.speed_select
        else:
            raise Exception("timer doesn't know WHAT the fuck to do")

    def bus_write(self, addr, value):
        if addr == 0: # DIV
            self.div_clock = 0
            self.clock = 0
        elif addr == 1: # TIMA
            self.clock = value & 0xFF
        elif addr == 2: # TMA
            self.load_value = value & 0xFF
        elif addr == 3: # TAC
            self.enabled = (value & 0x4) != 0
            self.speed_select = value & 0x3
        else:
            raise Exception("timer doesn't know WHAT the fuck to do")

class JOYPAD(bus.BUS_OBJECT):
    def __init__(self):
        super(JOYPAD, self).__init__()
        self.direction_select = False
        self.button_select = False
        self.directions = 0x0F
        self.buttons = 0x0F

        self.direction_idx = {
            "right": 0,
            "left": 1,
            "up": 2,
            "down": 3,
        }
        self.button_idx = {
            "a": 0,
            "b": 1,
            "select": 2,
            "start": 3,
        }
  
    def update(self, keys):
        changed = False
        for key, idx in self.direction_idx.items():
            if key in keys:
                if keys[key]:
                    self.directions &= ~(1 << idx)
                else:
                    self.directions |= 1 << idx
                changed = True
        for key, idx in self.button_idx.items():
            if key in keys:
                if keys[key]:
                    self.buttons &= ~(1 << idx)
                else:
                    self.buttons |= 1 << idx
                changed = True

        if changed:
            # Trigger an interrupt
            # This is technically only supposed to happen on high-to-low
            # transitions but because the real hardware buttons aren't
            # debounced it effectively happens on both button press and
            # release
            # TODO: pull these magic numbers out somewhere
            IF_state = self.bus.read(0xFF0F)
            IF_state |= 0x10
            self.bus.write(0xFF0F, IF_state)

    def bus_read(self, addr):
        if addr == 0:
            val = 0
            val |= self.button_select << 5
            val |= self.direction_select << 4
            if not self.direction_select:
                val |= self.directions
            if not self.button_select:
                val |= self.buttons
            return val
        else:
            raise Exception("joypad doesn't know WHAT the fuck to do")

    def bus_write(self, addr, value):
        if addr == 0:
            self.button_select = (value & (1 << 5)) != 0
            self.direction_select = (value & (1 << 4)) != 0
        else:
            raise Exception("joypad doesn't know WHAT the fuck to do")


if __name__=="__main__":
    if len(sys.argv) < 2:
        print "Usage: %s [-v] ROMFILE" % sys.argv[0]
        sys.exit(1)

    if "-v" in sys.argv:
        verbose = True
    else:
        verbose = False

    pygame.init()
    pygame.display.set_caption("pygb")
    pygame.key.set_repeat(10, 10)

    with open(sys.argv[1], "rb") as f:
        print "Building system"
        sysbus = bus.BUS()

        rom = ROM(f)
        sysbus.attach(rom, 0x0000, 0x3FFF)

        ram = [RAM(4096), RAM(4096)]
        sysbus.attach(ram[0], 0xC000, 0xCFFF)
        sysbus.attach(ram[1], 0xD000, 0xDFFF)

        hram = RAM(127)
        sysbus.attach(hram, 0xFF80, 0xFFFE)

        video_driver = video.VIDEO(sysbus)

        joypad = JOYPAD()
        sysbus.attach(joypad, 0xFF00, 0xFF00)

        if_reg = cpu.REG("IF", 8)
        sysbus.attach(if_reg, 0xFF0F, 0xFF0F)
        
        ie_reg = cpu.REG("IE", 8)
        sysbus.attach(ie_reg, 0xFFFF, 0xFFFF)

        timer = TIMER()
        sysbus.attach(timer, 0xFF04, 0xFF07)

        syscpu = cpu.CPU(sysbus)
        
        print "Starting execution"

        n_instr = 0
        n_cyc = 0
        T_start = time.time()
        while not syscpu._stopped:
            try:
                # TODO: double-check signed arithmetic everywhere. does C/H work
                # as borrow flags when doing SUB/DEC/etc?
                # TODO: implement the STOP instruction correctly

                if not syscpu._halted:
                    opcode = sysbus.read(syscpu.PC.read())
                    op = syscpu.decode(opcode)
                    cycles = op()
                else:
                    # NOP if halted
                    cycles = 1

                # TODO: not sure where/when/how often to do this, putting it here
                # for now so we only have to call timer.advance() once:
                cycles += syscpu.service_interrupts()

                T_op = syscpu.T_cyc * cycles
                timer.advance(T_op)

                # TODO: decompose this and allow for configurable keybindings
                keys = {}
                key_bindings = {
                    pygame.K_LEFT: "left",
                    pygame.K_RIGHT: "right",
                    pygame.K_UP: "up",
                    pygame.K_DOWN: "down",
                    pygame.K_z: "a",
                    pygame.K_x: "b",
                    pygame.K_RETURN: "start",
                    pygame.K_TAB: "select",
                }
                for event in pygame.event.get(): 
                    if event.type == pygame.QUIT: 
                        syscpu.op_stop()
                    elif event.type == pygame.KEYDOWN:
                        if event.key in key_bindings:
                            keys[key_bindings[event.key]] = True
                    elif event.type == pygame.KEYUP:
                        if event.key in key_bindings:
                            keys[key_bindings[event.key]] = False
                if len(keys) > 0:
                    joypad.update(keys)

                video_driver.advance(T_op)
                # TODO: make sure this DMA blockade covers MBCs once they're
                # implemented:
                if video_driver.dma_active():
                    rom.bus_enabled = False
                    for ram_bank in ram:
                        ram_bank.bus_enabled = False
                else:
                    rom.bus_enabled = True
                    for ram_bank in ram:
                        ram_bank.bus_enabled = True

                if verbose:
                    # TODO: core dump is showing 'next pc' and 'current regs'
                    print syscpu.core_dump()
                    print "------------"
            except:
                print "------------"
                print "CORE DUMP"
                print syscpu.core_dump()
                print "------------"
                raise

            n_instr += 1
            n_cyc += 1
        T_end = time.time()
        print "Executed %i instructions in %f seconds (%f simulated)" % (n_instr, T_end-T_start, n_cyc*syscpu.T_cyc)

