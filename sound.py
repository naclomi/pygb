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
    # TODO: duty cycle lookup table:
    #   duty = {0:.125, 1:.25, 2:.5, 3:.75}[reg]

class NoteSound(Sound):
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

class SynthChannel(object):
    def __init__(self, sample_rate, stereo = True):
        self.sample_rate = sample_rate
        self.n_channels = {True: 2, False: 1}[stereo]

        self.enabled = False

        # Length control -
        # Either an int representing the number of samples left in the 
        # note, or None representing an indefinite note
        self._length_counter = None

        # Volume envelope -
        # When envelope period is non-zero, the envelope is enabled:
        # Every period samples, increase or decrease the envelope value
        # by delta (either 1/steps or -1/steps) and saturate at 0 or 1.
        # Then multiply the final sound sample by the envelope value.
        self._volume_envelope_period = 0
        self._volume_envelope_counter = 0
        self._volume_envelope_steps = 15
        self._volume_envelope_delta = 0
        self._volume_envelope_value = 0

        self._data_buffer = array("f")

    def set_duration(self, seconds):
        if seconds is None:
            self._length_counter = None
        else:
            self._length_counter = int(self.sample_rate * seconds)

    def set_volume_envelope(self, initial_volume, increasing, period_seconds):
        self._volume_envelope_value = initial_volume
        self._volume_envelope_delta = 1.0/self._volume_envelope_steps
        if not increasing:
            self._volume_envelope_delta *= -1
        self._volume_envelope_period = int(self.sample_rate * period_seconds)
        self._volume_envelope_counter = self._volume_envelope_period

    def channel_function(self, n_samples, min_sample, max_sample):
        return False

    def gen_samples(self, n_words):
        if len(self._data_buffer) < n_words:
            self._data_buffer.extend([0]*n_words)

        if self.enabled:
            n_samples = n_words // self.n_channels 

            if self._length_counter is not None:
                if self._length_counter <= 0:
                    return None
                elif self._length_counter <= n_samples:
                    # Zero out the sound after the tone gets clipped
                    for time in range(self._length_counter, n_samples):
                        self._data_buffer[time*2] = 0 # L
                        self._data_buffer[time*2+1] = 0 # R
                    # Readjust the requested number of wave samples
                    # to stop at the clipping time
                    n_samples = self._length_counter
                    self._length_counter = 0
                else:
                    self._length_counter -= n_samples

            if self._volume_envelope_period > 0:
                # TODO: slightly inaccurate, this should run in the main
                # generation loop
                if self._volume_envelope_counter <= 0:
                    self._volume_envelope_counter = self._volume_envelope_period
                    self._volume_envelope_value += self._volume_envelope_delta
                    self._volume_envelope_value = max(self._volume_envelope_value, 0)
                    self._volume_envelope_value = min(self._volume_envelope_value, 1)
                else:
                    self._volume_envelope_counter -= n_samples
                max_sample = 0.5+(self._volume_envelope_value/2.0)
                min_sample = 0.5-(self._volume_envelope_value/2.0)
            else:
                max_sample = 1
                min_sample = 0

            if self.channel_function(n_samples, min_sample, max_sample):
                return self._data_buffer[:n_words]
            else:
                return None
        else:
            return None

class SquareChannel(SynthChannel):
    def __init__(self, *args, **kwargs):
        super(SquareChannel, self).__init__(*args, **kwargs)

        self.freq = 0
        self.duty = 0.5

        self._last_pos = 0

        # Frequency sweep - 
        # If sweep_period is non-zero, every period samples the
        # new note frequency f' is recalculated from the old frequency
        # f as such:
        # f' = f + coef*f
        # TODO:
        # "" Clearing the sweep negate mode bit in NR10 after at least one sweep
        # calculation has been made using the negate mode since the last trigger
        # causes the channel to be immediately disabled. This prevents you from
        # having the sweep lower the frequency then raise the frequency without a
        # trigger inbetween. ""
        self._freq_sweep_period = 0
        self._freq_sweep_coef = 0
        self._freq_sweep_counter = 0
        self._freq_sweep_effective = 0


    def set_freq_sweep(self, coef, period_seconds):
        self._freq_sweep_coef = coef
        self._freq_sweep_period = int(self.sample_rate * period_seconds)
        self._freq_sweep_counter = self._freq_sweep_period
        self._freq_sweep_effective = self.freq


    def channel_function(self, n_samples, min_sample, max_sample):
        if self.freq <= 0:
            return False

        if self._freq_sweep_period > 0:
            # TODO: slightly inaccurate, this should run in the main
            # generation loop
            if self._freq_sweep_counter <= 0:
                self._freq_sweep_counter = self._freq_sweep_period
                self._freq_sweep_effective += self._freq_sweep_coef * self._freq_sweep_effective
            else:
                self._freq_sweep_counter -= n_samples

            # TODO: this needs to be written back into the gameboy
            # registers somehow, and it must clobber any changes
            # since the sweep was triggered
            effective_freq = self._freq_sweep_effective
        else:
            effective_freq = self.freq

        if effective_freq > 2047:
            return False

        period = self.sample_rate // effective_freq

        # TODO: profile if this is faster than a normal python array
        for time in range(n_samples):
            if ((time+self._last_pos) % period) < period * self.duty:
                self._data_buffer[time*2] = max_sample # L
                self._data_buffer[time*2+1] = max_sample # R
            else:
                self._data_buffer[time*2] = min_sample # L
                self._data_buffer[time*2+1] = min_sample # R

        self._last_pos += n_samples
        self._last_pos %= period

        return True


class NoiseChannel(SynthChannel):
    def __init__(self, *args, **kwargs):
        super(NoiseChannel, self).__init__(*args, **kwargs)
        self.wide_mode = True 
        
        self._lfsr = 1
        self._update_counter = 0
        self._update_period_samples = 0

    def reset_lfsr(self):
        self._lfsr = 1

    def channel_function(self, n_samples, min_sample, max_sample):
        # The amplitude is randomly switched between high and low at the given frequency. A higher frequency will make the noise to appear 'softer'.
        # When Bit 3 is set, the output will become more regular, and some frequencies will sound more like Tone than Noise.
        #   Bit 7-4 - Shift Clock Frequency (s); max == 
        #   Bit 3   - Counter Step/Width (0=15 bits, 1=7 bits)
        #   Bit 2-0 - Dividing Ratio of Frequencies (r, )
        # Frequency = 524288 Hz / (r * 2^(s+1)) ;For r=0 assume r=0.5 instead
        #
        # The linear feedback shift register (LFSR) generates a pseudo-random
        # bit sequence. It has a 15-bit shift register with feedback. When
        # clocked by the frequency timer, the low two bits (0 and 1) are XORed,
        # all bits are shifted right by one, and the result of the XOR is put
        # into the now-empty high bit. If width mode is 1 (NR43), the XOR result
        # is ALSO put into bit 6 AFTER the shift, resulting in a 7-bit LFSR. The
        # waveform output is bit 0 of the LFSR, INVERTED.
        #
        # When initialized, all shift registers are set to 1. On each clock
        # pulse, bits are shifted from left to right (on the picture) s1 being
        # the least significant bit and the output that is sent to the channel's
        # envelope generator.
        #
        # From belogic:
        # 000: f*2
        # 001: f
        # 010: f/2
        # 011: f/3
        # 100: f/4
        # 101: f/5
        # 110: f/6
        # 111: f/7          Where f=4.194304 Mhz/8

        # 0000: Q/2
        # 0001: Q/2^2
        # 0010: Q/2^3
        # 0011: Q/2^4
        # ....
        # 1101: Q/2^14
        # 1110: Not used
        # 1111: Not used         Where Q is the clock divider's output
        #
        #
        # TODO: seems like the wave can flip anywhere from 12 times/sample
        #   to once every 9647 samples -- prepare for both contingencies

        self._update_counter += n_samples
        if self._update_counter > self._update_period_samples:
            xor = bool(self.lfsr & 0x1) ^ bool(self.lfsr & 0x2)
            self.lfsr = self.lfsr >> 1
            self.lfsr |= xor << 15
            if not self.wide_mode:
                self.lfsr |= xor << 6
            self._update_counter -= self._update_period_samples


        for time in range(n_samples):
            if ((time+self._last_pos) % period) < period * self.duty:
                self._data_buffer[time*2] = max_sample # L
                self._data_buffer[time*2+1] = max_sample # R
            else:
                self._data_buffer[time*2] = min_sample # L
                self._data_buffer[time*2+1] = min_sample # R




class GameboyMixerStream(object):
    def __init__(self, sample_rate = 44100, stereo = True, buffer_seconds = 1):
        self.n_channels = {True: 2, False: 1}[stereo]
        self.sample_rate = sample_rate
        self.sample_bytes = 2

        riff_buffer = io.BytesIO()

        w = wave.open(riff_buffer, "wb")
        w.setsampwidth(self.sample_bytes)
        w.setnchannels(self.n_channels)
        w.setframerate(self.sample_rate)
        sentinel_value = b"\xDA\x7A"
        # TODO: find some way to not have to allocate ALL of this memory:
        w.writeframes(sentinel_value * int(self.sample_bytes * self.sample_rate * buffer_seconds / len(sentinel_value)))
        w.close()

        tmp_riff_file = riff_buffer.getvalue()
        riff_data_offset = tmp_riff_file.index(sentinel_value)
        self.riff_header = tmp_riff_file[:riff_data_offset]
        riff_buffer.close()

        self._data_buffer = array("h")

        self.file_pos = 0
        self.max_file_pos = len(tmp_riff_file)

        self.square_a = SquareChannel(sample_rate, stereo)
        self.square_b = SquareChannel(sample_rate, stereo)
        # self.noise = NoiseChannel(sample_rate, stereo)

    def fill_data(self, n_words):
        if len(self._data_buffer) < n_words:
            self._data_buffer.extend([0]*n_words)

        sounds = [
            self.square_a.gen_samples(n_words),
            self.square_b.gen_samples(n_words),
            # self.noise.gen_samples(n_words)
        ]

        max_value_unsigned = (2 ** (self._data_buffer.itemsize*8) - 1)
        max_value_signed = max_value_unsigned // 2

        for idx in range(n_words):
            mix_normalized = 0
            for sound in sounds:
                if sound is not None:
                    mix_normalized = mix_normalized + sound[idx] - mix_normalized*sound[idx]
            mix_signed = int(mix_normalized * max_value_unsigned - max_value_signed - 1)
            # print(mix_signed)
            self._data_buffer[idx] = mix_signed

    def tell(self):
        # print("tell",self.file_pos)
        return self.file_pos

    def read(self, size=None):
        if size is None:
            raise ValueError("Mixer stream does not support unbounded reads")
        # print ("read ", self.file_pos, size)
        output_bytes = ""
        if self.file_pos < len(self.riff_header):
            if size <= len(self.riff_header) - self.file_pos:
                # print("encap")
                output_bytes = self.riff_header[self.file_pos:self.file_pos+size]
            else:
                # print("bleed")
                read_size_words = (size-len(self.riff_header)) // self._data_buffer.itemsize
                self.fill_data(read_size_words)
                output_bytes = self.riff_header[self.file_pos:] + self._data_buffer[:read_size_words].tostring()
        else:
            # print("data")
            read_size_words = size // self._data_buffer.itemsize
            self.fill_data(read_size_words)
            output_bytes = self._data_buffer[:read_size_words].tostring()

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


def flat_tone(driver):
    driver.square_a.freq=440
    driver.square_a.enabled = True
    sleep(2)

def flat_chord(driver):
    driver.square_a.freq=440
    driver.square_a.enabled = True
    driver.square_b.freq=445
    driver.square_b.enabled = True
    sleep(2)

def duty_sweep(driver):
    driver.square_a.freq=440
    driver.square_a.enabled = True
    for x in range(100):
        driver.square_a.duty = x/100.0

        sleep(.1)

def duration_train(driver):
    driver.square_a.freq=440
    driver.square_a.enabled = True
    for x in range(10):
        driver.square_a.set_duration((x/10.0)*0.25)
        sleep(.5)
    driver.square_a.set_duration(None)
    sleep(2.0)


def siren(driver):
    chirp = 0
    driver.square_a.enabled = True
    driver.square_b.enabled = True
    for _ in range(10):
        driver.square_a.freq=640-chirp
        driver.square_b.freq=645-chirp
        sleep(.1)

        chirp += 5
        driver.square_a.freq=440-chirp
        driver.square_b.freq=445-chirp
        sleep(.1)
        chirp += 5
    sleep(.2)

def volume_envelope_test(driver):
    params = [
        (1.0, False, 1/64.0),
        (0.0, True, 1/64.0),
        (0.5, False, 1/64.0),
        (0.5, True, 1/64.0),
        (1.0, False, 7/64.0),
        (0.0, True, 7/64.0),
    ]
    driver.square_a.enabled = True
    for idx, param_set in enumerate(params):
        print(idx)
        driver.square_a.freq=440
        driver.square_a.set_volume_envelope(*param_set)
        sleep(3)
        driver.square_a.freq=0
        sleep(.25)


def freq_sweep_test(driver):
    params = [
        (1.0/(2**2), 4/128.0),
    ]
    driver.square_a.enabled = True
    for idx, param_set in enumerate(params):
        print(idx)
        driver.square_a.freq=440
        driver.square_a.set_freq_sweep(*param_set)
        sleep(1)
        driver.square_a.freq=0
        sleep(.25)

def noise_test(driver):
    pass

if __name__ == "__main__":
    pre_init(44100, -16, 1, 1024)
    pygame.init()

    pcm_stream = GameboyMixerStream(sample_rate = get_init()[0])
    pygame.mixer.music.set_volume(0.05)
    pcm_stream.connect()

    siren(pcm_stream)
