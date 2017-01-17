import bus
import cpu

from array import array
from time import sleep

import pygame
from pygame.mixer import Sound, get_init, pre_init

class SOUND(object):
    def __init__(self, bus):
        self.bus = bus

        # Dummy regs for now
        dummies = [
            (0xFF10, "NR10", 0x80),
            (0xFF11, "NR11", 0xBF),
            (0xFF12, "NR12", 0xF3),
            (0xFF13, "NR13", 0x00),
            (0xFF14, "NR14", 0xBF),

            (0xFF16, "NR21", 0x3F),
            (0xFF17, "NR22", 0x00),
            (0xFF18, "NR23", 0x00),
            (0xFF19, "NR24", 0xBF),

            (0xFF1A, "NR30", 0x7F),
            (0xFF1B, "NR31", 0xFF),
            (0xFF1C, "NR32", 0x9F),
            (0xFF1D, "NR33", 0xBF), #TODO: docs are very inconsistent about NR33's address/init value; double check what's going on
            (0xFF1E, "NR34", 0x00),

            (0xFF30, "WAV0", 0x00),
            (0xFF31, "WAV1", 0x00),
            (0xFF32, "WAV2", 0x00),
            (0xFF33, "WAV3", 0x00),
            (0xFF34, "WAV4", 0x00),
            (0xFF35, "WAV5", 0x00),
            (0xFF36, "WAV6", 0x00),
            (0xFF37, "WAV7", 0x00),
            (0xFF38, "WAV8", 0x00),
            (0xFF39, "WAV9", 0x00),
            (0xFF3A, "WAV10", 0x00),
            (0xFF3B, "WAV11", 0x00),
            (0xFF3C, "WAV12", 0x00),
            (0xFF3D, "WAV13", 0x00),
            (0xFF3E, "WAV14", 0x00),
            (0xFF3F, "WAV15", 0x00),

            (0xFF20, "NR41", 0xFF),
            (0xFF21, "NR42", 0x00),
            (0xFF22, "NR43", 0x00),
            (0xFF23, "NR44", 0xBF),

            (0xFF24, "NR50", 0x77),
            (0xFF25, "NR51", 0xF3),
            (0xFF26, "NR52", 0xF1),
        ]

        for reg in dummies:
            self.bus.attach(cpu.REG(reg[1], 8, init=reg[2]), reg[0], reg[0])    

    # TODO: reset()


class Note(Sound):
    # TODO: actually do this stuff
    def __init__(self, frequency, volume=.1):
        self.frequency = frequency
        Sound.__init__(self, self.build_samples())
        self.set_volume(volume)

    def build_samples(self):
        period = int(round(get_init()[0] / self.frequency))
        samples = array("h", [0] * period)
        amplitude = 2 ** (abs(get_init()[1]) - 1) - 1
        for time in xrange(period):
            if time < period / 2:
                samples[time] = amplitude
            else:
                samples[time] = -amplitude
        return samples



if __name__ == "__main__":
    pre_init(44100, -16, 1, 1024)
    pygame.init()
    Note(440,.01).play(-1)
    sleep(5)