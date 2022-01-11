import bus
import cpu

from array import array
from time import sleep
import struct
import io
import wave

import pygame
from pygame.mixer import Sound, music, get_init, pre_init

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
                self.freq = self._freq_sweep_effective
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
        self._wide_mode = True 
        
        self._lfsr = 0b1111111111111111
        self._update_counter = 0
        self._update_period_samples = 0

    def reset_lfsr(self):
        self._lfsr = 0b1111111111111111

    def set_params(self, r, s, wide):
        self._wide_mode = wide
        r = max(0.5, min(7, r))
        s = max(0, min(13, s))
        update_frequency = int(524288.0 / (r * 2**(s+1)))
        self._update_period_samples = self.sample_rate / update_frequency

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


        if self._update_period_samples == 0:
            return False

        time = 0
        while time < n_samples:
            period_samples = min(
                n_samples - time,
                self._update_period_samples - self._update_counter
            )

            if (self._lfsr & 0x1) == True:
                period_value = min_sample
            else:
                period_value = max_sample
           
            for i in range(int(time), int(time + period_samples)):
                self._data_buffer[i*2] = period_value
                self._data_buffer[i*2+1] = period_value
            time += period_samples
            self._update_counter += period_samples

            # print(period_samples, self._update_counter)
            if self._update_counter >= self._update_period_samples:
                # print("------------------------------")
                # print (bin(self._lfsr)[2:].rjust(16,"0"))
                xor = bool(self._lfsr & 0x1) ^ bool(self._lfsr & 0x2)
                self._lfsr = self._lfsr >> 1
                self._lfsr |= xor << 14
                if not self._wide_mode:
                    self._lfsr |= xor << 6
                self._update_counter -= self._update_period_samples

        return True



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
        self.noise = NoiseChannel(sample_rate, stereo)

        self.master_volume = (1,1)

    def set_master_volume(self, left, right):
        self.master_volume = (left, right)

    def fill_data(self, n_words):
        if len(self._data_buffer) < n_words:
            self._data_buffer.extend([0]*n_words)

        sounds = [
            self.square_a.gen_samples(n_words),
            self.square_b.gen_samples(n_words),
            self.noise.gen_samples(n_words)
        ]

        max_value_unsigned = (2 ** (self._data_buffer.itemsize*8) - 1)

        master_left_scale = max_value_unsigned * self.master_volume[0]
        master_right_scale = max_value_unsigned * self.master_volume[1]

        # TODO: this might produce weird results when master volume is 0 -- double-check
        master_left_offset = (master_left_scale // 2) + 1
        master_right_offset = (master_right_scale // 2) + 1

        for idx in range(0,n_words,2):
            mix_left_normalized = 0
            mix_right_normalized = 0
            for sound in sounds:
                if sound is not None:
                    mix_left_normalized = mix_left_normalized + sound[idx] - mix_left_normalized*sound[idx]
                    mix_right_normalized = mix_right_normalized + sound[idx+1] - mix_right_normalized*sound[idx+1]
            # print(mix_signed)
            self._data_buffer[idx] = int(mix_left_normalized * master_left_scale - master_left_offset)
            self._data_buffer[idx+1] = int(mix_right_normalized * master_right_scale - master_right_offset)

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
                output_bytes = self.riff_header[self.file_pos:] + self._data_buffer[:read_size_words].tobytes()
        else:
            # print("data")
            read_size_words = size // self._data_buffer.itemsize
            self.fill_data(read_size_words)
            output_bytes = self._data_buffer[:read_size_words].tobytes()

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

    def disconnect(self):
        pygame.mixer.music.stop()


class SOUND(object):
    def __init__(self, bus):
        self.bus = bus
        bus.attach(self, 0xFF10, 0xFF26)

        self.pcm_stream = GameboyMixerStream(sample_rate = get_init()[0])
        pcm_stream.connect()
        # TODO: need to disconnect at some point

        self.reg_values = {}

    def reset(self):
        defaults = [
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
        for default in defaults:
            self.reg_values[default[0]-0xFF10] = default[2]
        # TODO: reset actual audio units

    def bus_read(self, addr):
        # TODO:
        # Reading NR52 yields the current power status and each channel's enabled status (from the length counter).
        # Wave RAM reads back as the last value written.
        # When an NRxx register is read back, the last written value ORed with the following is returned:
        #      NRx0 NRx1 NRx2 NRx3 NRx4
        #     ---------------------------
        # NR1x  $80  $3F $00  $FF  $BF 
        # NR2x  $FF  $3F $00  $FF  $BF 
        # NR3x  $7F  $FF $9F  $FF  $BF 
        # NR4x  $FF  $FF $00  $00  $BF 
        # NR5x  $00  $00 $70
        # $FF27-$FF2F always read back as $FF
        # That is, the channel length counters, frequencies, and unused bits always read back as set to all 1s.

        if addr == 0: # 0xFF10 NR10
            return self.reg_values[addr] | 0x80
        elif addr == 1: # 0xFF10 NR11
            #   Bit 7-6 - Wave Pattern Duty (Read/Write)
            #   Bit 5-0 - Sound length data (Write Only) (t1: 0-63)
            # Wave Duty:
            #   00: 12.5% ( _-------_-------_------- )
            #   01: 25%   ( __------__------__------ )
            #   10: 50%   ( ____----____----____---- ) (normal)
            #   11: 75%   ( ______--______--______-- )
            # Sound Length = (64-t1)*(1/256) seconds
            # The Length value is used only if Bit 6 in NR14 is set.
            return self.reg_values[addr] | 0x3F
        elif addr == 2: # 0xFF10 NR12
            #   Bit 7-4 - Initial Volume of envelope (0-0Fh) (0=No Sound)
            #   Bit 3   - Envelope Direction (0=Decrease, 1=Increase)
            #   Bit 2-0 - Number of envelope sweep (n: 0-7)
            #             (If zero, stop envelope operation.)
            # Length of 1 step = n*(1/64) seconds
            return self.reg_values[addr]
        elif addr == 3: # 0xFF10 NR13
            # Lower 8 bits of 11 bit frequency (x).
            # Next 3 bit are in NR14 ($FF14)
            return 0xFF
        elif addr == 4: # 0xFF10 NR14
            #   Bit 7   - Initial (1=Restart Sound)     (Write Only)
            #   Bit 6   - Counter/consecutive selection (Read/Write)
            #             (1=Stop output when length in NR11 expires)
            #   Bit 2-0 - Frequency's higher 3 bits (x) (Write Only)
            # Frequency = 131072/(2048-x) Hz
            return self.reg_values[addr] | 0xBF
        elif addr == 20: # 0xFF24 NR50        
            # Bit 7   - Output Vin to SO2 terminal (1=Enable)
            # Bit 6-4 - SO2 output level (volume)  (0-7)
            # Bit 3   - Output Vin to SO1 terminal (1=Enable)
            # Bit 2-0 - SO1 output level (volume)  (0-7)
            return self.reg_values[addr]
        else:
            raise Exception("audio driver doesn't know WHAT the fuck to do")


    def bus_write(self, addr, value):
        if addr == 0: # 0xFF10 NR10
            # FF10 - NR10 - Channel 1 Sweep register (R/W)
            #   Bit 6-4 - Sweep Time
            #   Bit 3   - Sweep Increase/Decrease
            #              0: Addition    (frequency increases)
            #              1: Subtraction (frequency decreases)
            #   Bit 2-0 - Number of sweep shift (n: 0-7)
            # Sweep Time:
            #   000: sweep off - no freq change
            #   001: 7.8 ms  (1/128Hz)
            #   010: 15.6 ms (2/128Hz)
            #   011: 23.4 ms (3/128Hz)
            #   100: 31.3 ms (4/128Hz)
            #   101: 39.1 ms (5/128Hz)
            #   110: 46.9 ms (6/128Hz)
            #   111: 54.7 ms (7/128Hz)

            # The change of frequency (NR13,NR14) at each shift is calculated by the following formula where X(0) is initial freq & X(t-1) is last freq:
            #   X(t) = X(t-1) +/- X(t-1)/2^n
            self.reg_values[addr] = value & 0xFF
            coef = 1/(2**(value & 0b111))
            if (value & 0b1000) != 0:
                coef = -coef
            period = ((value >> 4) & 0b111) / 128
            self.pcm_stream.square_a.set_freq_sweep(coef, period)
        elif addr == 1: # 0xFF10 NR11
            #   Bit 7-6 - Wave Pattern Duty (Read/Write)
            #   Bit 5-0 - Sound length data (Write Only) (t1: 0-63)
            # Wave Duty:
            #   00: 12.5% ( _-------_-------_------- )
            #   01: 25%   ( __------__------__------ )
            #   10: 50%   ( ____----____----____---- ) (normal)
            #   11: 75%   ( ______--______--______-- )
            # Sound Length = (64-t1)*(1/256) seconds
            # The Length value is used only if Bit 6 in NR14 is set.
            self.reg_values[addr] = value & 0xFF
            duty_code = (value>>6) & 0x03
            duty_value = [.125, .25, .5, .75][duty_code]
            self.pcm_stream.square_a.duty = duty_value
            pass
        elif addr == 2: # 0xFF10 NR12
            #   Bit 7-4 - Initial Volume of envelope (0-0Fh) (0=No Sound)
            #   Bit 3   - Envelope Direction (0=Decrease, 1=Increase)
            #   Bit 2-0 - Number of envelope sweep (n: 0-7)
            #             (If zero, stop envelope operation.)
            # Length of 1 step = n*(1/64) seconds
            pass
        elif addr == 3: # 0xFF10 NR13
            # Lower 8 bits of 11 bit frequency (x).
            # Next 3 bit are in NR14 ($FF14)
            pass
        elif addr == 4: # 0xFF10 NR14
            #   Bit 7   - Initial (1=Restart Sound)     (Write Only)
            #   Bit 6   - Counter/consecutive selection (Read/Write)
            #             (1=Stop output when length in NR11 expires)
            #   Bit 2-0 - Frequency's higher 3 bits (x) (Write Only)
            # Frequency = 131072/(2048-x) Hz
            pass
        elif addr == 20: # 0xFF24 NR50        
            # NR50 FF24 ALLL BRRR Vin L enable, Left vol, Vin R enable, Right vol
            self.reg_values[addr] = value & 0xFF
            vol_r = (value & 0b111)//0b111
            vol_l = ((value>>4) & 0b111)//0b111
            self.pcm_stream.set_master_volume(vol_l, vol_r)
        if addr == 21: # 0xFF25 NR51
            # NR51 FF25 NW21 NW21 Left enables, Right enables
            # TODO
            pass
        if addr == 22: # 0xFF26 NR52
            # NR52 FF26 P--- NW21 Power control/status, Channel length statuses
            # TODO
            pass
        else:
            raise Exception("audio driver doesn't know WHAT the fuck to do")


    # TODO: duty cycle lookup table:
    #   duty = {0:.125, 1:.25, 2:.5, 3:.75}[reg]

#################################
# Sound tests:

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
    driver.noise.reset_lfsr()
    driver.noise.set_params(6,2,True)
    driver.noise.enabled = True
    sleep(2)

if __name__ == "__main__":
    import sys


    tests = [siren, noise_test, freq_sweep_test, volume_envelope_test, duration_train, duty_sweep, flat_chord, flat_tone]
    if len(sys.argv) >= 2:
        pre_init(44100, -16, 1, 1024)
        pygame.init()

        pcm_stream = GameboyMixerStream(sample_rate = get_init()[0])
        pcm_stream.set_master_volume(0.05,0.05)
        pcm_stream.connect()

        for test_idx in sys.argv[1:]:
            tests[int(test_idx,0)](pcm_stream)

        pcm_stream.disconnect()
        print("exit")
    else:
        print("usage: {:} TEST_NUMBER ...".format(sys.argv[0]))
        print("Available tests:")
        for idx, test in enumerate(tests):
            print(str(idx) + ". " + test.__name__)


