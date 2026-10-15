import logging
import threading
import time
import warnings
from .models import audio_energy

log = logging.getLogger(__name__)


class AudioMeter:
    """Optional WASAPI output loopback. No microphone, storage or transmission."""
    def __init__(self):
        self.enabled = False
        self.level = 0.0
        self.error = ""
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="Halo output meter", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            if not self.enabled:
                self.level = 0.0
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
                        check_at = time.monotonic() + 3
                        while self.enabled and not self.stop_event.is_set():
                            samples = recorder.record(numframes=1024)
                            self.level = audio_energy(samples)
                            if time.monotonic() > check_at:
                                check_at = time.monotonic() + 3
                                if sc.default_speaker().id != speaker.id:
                                    break
            except Exception:
                log.debug("Audio-reactive mode unavailable", exc_info=True)
                self.level = 0
                self.error = "Audio output unavailable; using gentle motion."
                self.stop_event.wait(3)

    def close(self):
        self.stop_event.set()
