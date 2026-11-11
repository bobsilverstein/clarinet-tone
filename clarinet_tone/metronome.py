"""Metronome click played only to the Bluetooth headset.

The click starts with Record, stops with Stop or Discard, and pauses with Pause.
Clicks are placed sample-exactly by counting samples in the audio callback, so
the tempo never drifts.  The first beat of each bar is accented (higher and louder).
"""
from __future__ import annotations

import threading

import numpy as np

from .config import SAMPLE_RATE

# Host APIs in order of preference for output.
_HOST_ORDER = ["Windows DirectSound", "MME", "Windows WASAPI", "Windows WDM-KS"]


def _sd():
    import sounddevice
    return sounddevice


def find_headset(hints: str):
    """(device index, name) of the first headset found, or None.  hints lists parts of
    the headsets' names, separated by commas, first choice first (Shokz, then Sony).
    Windows lists a Bluetooth headset twice: "Headphones (…)" for stereo music and
    "Headset (…)" for calls.  The calls profile lowers sound quality and can take
    over the microphone, so "Headphones" comes first."""
    sd = _sd()
    hints = [h.strip().lower() for h in (hints or "").split(",") if h.strip()]
    if not hints:
        return None
    apis = sd.query_hostapis()
    cands = []
    for i, d in enumerate(sd.query_devices()):
        name = d["name"].lower()
        which = next((k for k, h in enumerate(hints) if h in name), None)
        if d["max_output_channels"] > 0 and which is not None:
            api = apis[d["hostapi"]]["name"]
            calls = "headset" in name and "headphone" not in name
            rank = (which, calls, _HOST_ORDER.index(api) if api in _HOST_ORDER else 99)
            cands.append((rank, i, d["name"]))
    for _, i, name in sorted(cands):
        try:
            sd.check_output_settings(device=i, channels=1, samplerate=SAMPLE_RATE, dtype="float32")
            return i, name
        except Exception:
            continue
    return None


def _click(freq: float, amp: float, ms: float = 25.0) -> np.ndarray:
    n = int(SAMPLE_RATE * ms / 1000)
    t = np.arange(n) / SAMPLE_RATE
    env = np.exp(-t / (ms / 1000 / 5))
    return (amp * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# Bob's pattern (2026-11-10): beat 1 strong and highest; beats 2 and 4 much quieter;
# beat 3 a bit louder and higher than 2 and 4, but below beat 1.
FULL = 0.9
ACCENT = _click(2000.0, FULL)                       # beat 1
MIDDLE = _click(1600.0, FULL * 10 ** (-4 / 20))     # beat 3 of 4/4: 4 dB below beat 1
BEAT = _click(1200.0, FULL * 10 ** (-9 / 20))       # beats 2 and 4: 9 dB below beat 1


def sound_for(k: int, beats: int) -> np.ndarray:
    """Click for beat number k (0 = first beat of the take)."""
    b = k % beats
    if b == 0:
        return ACCENT
    if beats == 4 and b == 2:
        return MIDDLE
    return BEAT


class Metronome:
    def __init__(self, device: int, name: str):
        self.device, self.name = device, name
        self._stream = None
        self._lock = threading.Lock()
        self.bpm, self.beats = 0, 0
        self._pos = 0               # samples since the first beat
        self._paused = False

    @property
    def running(self) -> bool:
        return self._stream is not None

    def start(self, bpm: int, beats: int) -> None:
        self.stop()
        if bpm <= 0:
            return
        self.bpm, self.beats = bpm, max(1, beats)
        self._pos, self._paused = 0, False
        sd = _sd()
        self._stream = sd.OutputStream(device=self.device, channels=1, samplerate=SAMPLE_RATE,
                                       dtype="float32", blocksize=512, callback=self._callback)
        self._stream.start()

    def pause(self, paused: bool) -> None:
        """While paused the click is silent; on resume it starts again from beat 1."""
        with self._lock:
            self._paused = paused
            if not paused:
                self._pos = 0

    def stop(self) -> None:
        st, self._stream = self._stream, None
        if st is not None:
            for f in (st.abort, st.close):
                try:
                    f()
                except Exception:
                    pass

    def render(self, frames: int) -> np.ndarray:
        """The next block of click sound (also used by the tests)."""
        out = np.zeros(frames, np.float32)
        with self._lock:
            if self._paused or self.bpm <= 0:
                return out
            period = SAMPLE_RATE * 60.0 / self.bpm
            start, end = self._pos, self._pos + frames
            # every beat whose click overlaps this block
            k = max(0, int(np.floor((start - len(ACCENT)) / period)) + 1)
            while True:
                b0 = int(round(k * period))
                if b0 >= end:
                    break
                c = sound_for(k, self.beats)
                lo, hi = max(start, b0), min(end, b0 + len(c))
                if hi > lo:
                    out[lo - start:hi - start] += c[lo - b0:hi - b0]
                k += 1
            self._pos = end
        return out

    def _callback(self, outdata, frames, time_info, status):
        outdata[:, 0] = self.render(frames)
