import logging
import math
import threading
import time
import warnings
import numpy as np
from .models import audio_energy

log = logging.getLogger(__name__)


class AudioDynamics:
    """Volume-adaptive bass/percussion accents from a bounded local audio window.

    This detects energy onsets, not tempo or a predicted beat grid. Channels
    are analysed as power, so opposite-phase stereo cannot cancel the signal.
    Only the last 2048 frames are retained, never a recording of the track.
    """
    def __init__(self, samplerate=48000):
        self.samplerate = samplerate
        self.size = 2048
        self.window = np.hanning(self.size)
        self.scale = 2 / (self.size * float(np.sum(self.window ** 2)))
        frequencies = np.fft.rfftfreq(self.size, 1 / samplerate)
        self.bass_bins = (frequencies >= 35) & (frequencies < 230)
        edges = (35, 90, 250, 700, 2000, 6000, 16000)
        self.band_bins = [(frequencies >= a) & (frequencies < b)
                          for a, b in zip(edges, edges[1:])]
        self.tail = None
        self.previous_bands = None
        self.reference = self.slow_rms = self.slow_bass = 0.
        self.rms = self.accent = self.level = 0.

    def process(self, samples):
        frames = np.asarray(samples, dtype=np.float64)
        if not frames.size:
            return self.level
        if frames.ndim == 1:
            frames = frames[:, None]
        if frames.ndim != 2:
            raise ValueError("Audio samples must be frames by channels")
        frames = np.nan_to_num(frames, nan=0., posinf=0., neginf=0.)
        elapsed = len(frames) / self.samplerate
        self.rms = audio_energy(frames)
        noise_floor = .00002
        self.reference = max(self.rms, self.reference * math.exp(-elapsed / 1.5))
        normalized = min(1., self.rms / max(noise_floor, self.reference))
        bed = (.08 + .12 * normalized) if self.rms > noise_floor else 0.
        if self.tail is None or self.tail.shape[1] != frames.shape[1]:
            self.tail = frames[-self.size:].copy()
            self.previous_bands = None
            self.slow_rms = self.rms
            self.slow_bass = 0.
        else:
            self.tail = np.concatenate((self.tail, frames))[-self.size:]
        onset = 0.
        if len(self.tail) == self.size:
            spectrum = np.fft.rfft(self.tail * self.window[:, None], axis=0)
            power = np.mean(spectrum.real ** 2 + spectrum.imag ** 2, axis=1) * self.scale
            bass = math.sqrt(float(np.sum(power[self.bass_bins])))
            bands = np.array([math.sqrt(float(np.sum(power[mask]))) for mask in self.band_bins])
            if self.previous_bands is not None and self.rms > noise_floor:
                rise = max(0., self.rms - self.slow_rms * 1.05) / max(self.slow_rms, self.reference * .1, noise_floor)
                bass_rise = max(0., bass - self.slow_bass * 1.06) / max(self.slow_bass, self.reference * .06, noise_floor)
                flux = float(np.maximum(0., bands - self.previous_bands).sum()) / max(float(self.previous_bands.sum()), self.reference * .3, noise_floor)
                onset = min(1., max(0., (max(rise * 3, bass_rise * 4, flux * 4) - .12) / .88))
            else:
                self.slow_bass = bass
            self.previous_bands = bands
            amount = 1 - math.exp(-elapsed / .23)
            self.slow_bass += (bass - self.slow_bass) * amount
        amount = 1 - math.exp(-elapsed / .23)
        self.slow_rms += (self.rms - self.slow_rms) * amount
        self.accent = max(onset, self.accent * math.exp(-elapsed / .08))
        self.level = min(1., max(bed, self.accent))
        return self.level


class AudioMeter:
    """Optional WASAPI output loopback. No microphone, storage or transmission."""
    def __init__(self):
        self.enabled = False
        self.level = 0.0
        self.raw_level = 0.0
        self.error = ""
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="Halo output meter", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            if not self.enabled:
                self.level = 0.0
                self.raw_level = 0.0
                self.stop_event.wait(.2)
                continue
            try:
                import soundcard as sc
                speaker = sc.default_speaker()
                mic = sc.get_microphone(id=speaker.id, include_loopback=True)
                self.error = ""
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", sc.SoundcardRuntimeWarning)
                    with mic.recorder(samplerate=48000, blocksize=2048) as recorder:
                        dynamics = AudioDynamics(48000)
                        check_at = time.monotonic() + 3
                        while self.enabled and not self.stop_event.is_set():
                            samples = recorder.record(numframes=1024)
                            self.level = dynamics.process(samples)
                            self.raw_level = dynamics.rms
                            if time.monotonic() > check_at:
                                check_at = time.monotonic() + 3
                                if sc.default_speaker().id != speaker.id:
                                    break
            except Exception:
                log.debug("Audio-reactive mode unavailable", exc_info=True)
                self.level = 0
                self.raw_level = 0
                self.error = "Audio output unavailable; using gentle motion."
                self.stop_event.wait(3)

    def close(self):
        self.stop_event.set()
