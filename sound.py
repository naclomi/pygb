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

# general pattern that data is read:
# stream.tell(), read args (eg, size), read kwargs (eg, none) 
# 0 (4,) {}
# 4 (8,) {}
# 0 (4,) {}
# 0 (4,) {}
# 4 (4,) {}
# 8 (4,) {}
# 12 (4,) {}
# 16 (4,) {}
# 20 (16,) {}
# 36 (4,) {}
# 40 (4,) {}
# 44 (2048,) {}
# 2092 (2048,) {}
# 4140 (2048,) {}
# 6188 (2048,) {}
# 8236 (2048,) {}
# ...
# 77868 (2048,) {}
# 79916 (2048,) {}
# 81964 (2048,) {}
# 84012 (2048,) {}
# 86060 (2048,) {}
# 88108 (136,) {}
# 44 (1912,) {}
# 1956 (2048,) {}
# 4004 (2048,) {}
# ...
# 81828 (2048,) {}
# 83876 (2048,) {}
# 85924 (2048,) {}
# 87972 (272,) {}
# 44 (1776,) {}
# ...

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
        print(self.riff_buffer.tell(), args, kwargs)
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

############################################################

class GameboyMixerStream(object):
    def __init__(self, sample_rate = 44100, stereo = True, buffer_seconds = 1):
        self.n_channels = {True: 2, False: 1}[stereo]
        self.sample_rate = sample_rate
        self.sample_bytes = 2
        self.buffer_seconds = buffer_seconds

        riff_buffer = io.BytesIO()

        w = wave.open(riff_buffer, "wb")
        w.setsampwidth(self.sample_bytes)
        w.setnchannels(self.n_channels)
        w.setframerate(self.sample_rate)
        sentinel_value = b"\xDA\x7A"
        # TODO: find some way to not have to allocate ALL of this memory:
        w.writeframes(sentinel_value * int(self.sample_bytes * self.sample_rate * self.buffer_seconds / len(sentinel_value)))
        w.close()

        tmp_riff_file = riff_buffer.getvalue()
        riff_data_offset = tmp_riff_file.index(sentinel_value)
        self.riff_header = tmp_riff_file[:riff_data_offset]
        riff_buffer.close()

        self.read_buffer = array("h")

        self.file_pos = 0
        self.max_file_pos = len(tmp_riff_file)

        self._tmp_gen_freq = 0
        self._tmp_last_pos = 0

    def _tmp_set_freq(self, f):
        self._tmp_gen_freq = f

    def fill_data(self, n_words):
        period = self.sample_rate // self._tmp_gen_freq
        n_samples = n_words // self.n_channels 
        amplitude = ((2 ** (self.read_buffer.itemsize*8)) // 2) - 1
        for time in range(n_samples):
            if ((time+self._tmp_last_pos) % period) < period / 2:
                self.read_buffer[time] = amplitude
            else:
                self.read_buffer[time] = -amplitude

        self._tmp_last_pos += n_samples
        self._tmp_last_pos %= period

    def tell(self):
        # print("tell",self.file_pos)
        return self.file_pos

    def read(self, size=None):
        if size is None:
            raise ValueError("Mixer stream does not support unbounded reads")
        if len(self.read_buffer) < size:
            self.read_buffer.extend([0]*size)
        # print ("read ", self.file_pos, size)
        output_bytes = ""
        if self.file_pos < len(self.riff_header):
            if size <= len(self.riff_header) - self.file_pos:
                # print("encap")
                output_bytes = self.riff_header[self.file_pos:self.file_pos+size]
            else:
                # print("bleed")
                read_size_words = (size-len(self.riff_header)) // self.read_buffer.itemsize
                self.fill_data(read_size_words)
                output_bytes = self.riff_header[self.file_pos:] + self.read_buffer[:read_size_words].tostring()
        else:
            # print("data")
            read_size_words = size // self.read_buffer.itemsize
            self.fill_data(read_size_words)
            output_bytes = self.read_buffer[:read_size_words].tostring()

        self.file_pos += size
        return output_bytes

    def seek(self, offset, whence=io.SEEK_SET):
        # print ("seek ",offset, whence)
        if whence == io.SEEK_SET:
            self.file_pos = offset
        elif whence == io.SEEK_CUR:
            self.file_pos += offset
        elif whence == io.SEEK_END:
            self.file_pos = self.max_file_pos + offset
        else:
            raise ValueError("Bad value for whence argument")

    def connect(self):
        pygame.mixer.music.load(self)
        pygame.mixer.music.play(loops=-1)


if __name__ == "__main__":
    pre_init(44100, -16, 1, 1024)
    pygame.init()
    # Note(440,.001).play(-1)

    pcm_stream = GameboyMixerStream(sample_rate = get_init()[0], stereo = False)
    
    # wave_data(440, pcm_stream.buffer_seconds, pcm_stream.sample_buffer())
    pcm_stream._tmp_set_freq(440)

    pygame.mixer.music.set_volume(0.05)
    pcm_stream.connect()
    chirp = 0
    for _ in range(10):
        sleep(.08)
        # wave_data(640-chirp, pcm_stream.buffer_seconds, pcm_stream.sample_buffer())
        pcm_stream._tmp_set_freq(640-chirp)
        chirp += 5
        sleep(.08)
        # wave_data(440-chirp, pcm_stream.buffer_seconds, pcm_stream.sample_buffer())
        pcm_stream._tmp_set_freq(440-chirp)
        chirp += 5
    sleep(.2)
    # sleep(5)


