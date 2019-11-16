import bus
import cpu

from array import array
from time import sleep
import struct
import io
import wave

import pygame
from pygame.mixer import Sound, music, get_init, pre_init

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
        Sound.__init__(self, buffer=self.build_samples())
        self.set_volume(volume)

    def build_samples(self):
        period = int(round(get_init()[0] / self.frequency))
        samples = array("h", [0] * period)
        amplitude = 2 ** (abs(get_init()[1]) - 1) - 1
        for time in range(period):
            if time < period / 2:
                samples[time] = amplitude
            else:
                samples[time] = -amplitude
        return samples

class RawPCMStream(object):
    def __init__(self, sample_rate = 44100, stereo = True, buffer_seconds = 1):
        self.n_channels = {True: 2, False: 1}[stereo]
        self.sample_rate = sample_rate
        self.sample_bytes = 2
        self.buffer_seconds = buffer_seconds

        self.riff_buffer = io.BytesIO()

        w = wave.open(self.riff_buffer, "wb")
        w.setsampwidth(self.sample_bytes)
        w.setnchannels(self.n_channels)
        w.setframerate(self.sample_rate)
        sentinel_value = b"\xDA\x7A"
        w.writeframes(sentinel_value * int(self.sample_bytes * self.sample_rate * self.buffer_seconds / len(sentinel_value)))
        w.close()
        self.riff_buffer.seek(0)

        self.riff_data_offset = self.riff_buffer.getvalue().index(sentinel_value)

        self.data_buffer = self.riff_buffer.getbuffer()[self.riff_data_offset:].cast('h')

    def sample_buffer(self):
        return self.data_buffer

    def tell(self, *args, **kwargs):
        return self.riff_buffer.tell(*args, **kwargs)

    def read(self, *args, **kwargs):
        return self.riff_buffer.read(*args, **kwargs)

    def seek(self, *args, **kwargs):
        return self.riff_buffer.seek(*args, **kwargs)

    def connect(self):
        pygame.mixer.music.load(self)
        pygame.mixer.music.play(loops=-1)


def wave_data(freq, n_seconds, data_buffer):
    period = int(round(get_init()[0] / freq))
    n_samples = get_init()[0] * n_seconds
    amplitude = 2 ** (abs(get_init()[1]) - 1) - 1
    for time in range(n_samples):
        if (time % period) < period / 2:
            data_buffer[time] = amplitude
        else:
            data_buffer[time] = -amplitude

if __name__ == "__main__":
    pre_init(44100, -16, 1, 1024)
    pygame.init()
    # Note(440,.001).play(-1)
    # pygame.mixer.music.load(GameboyMixerStream(44100, 440))

    pcm_stream = RawPCMStream(sample_rate = get_init()[0], stereo = False)

    wave_data(440, pcm_stream.buffer_seconds, pcm_stream.sample_buffer())

    pygame.mixer.music.set_volume(0.05)
    pcm_stream.connect()

    for _ in range(10):
        sleep(.04)
        wave_data(640, pcm_stream.buffer_seconds, pcm_stream.sample_buffer())
        sleep(.04)
        wave_data(440, pcm_stream.buffer_seconds, pcm_stream.sample_buffer())
    sleep(.2)


