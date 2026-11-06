"""Recording: microphone selection, 24-bit WAV writing, level metering, pause."""
import json
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import SAMPLE_RATE, SUBTYPE, MIC_HINT

# Host APIs in order of preference.  DirectSound and MME convert the
# Snowball's native 44.1 kHz to 48 kHz without fuss.
_HOST_ORDER = ["Windows DirectSound", "MME", "Windows WASAPI", "Windows WDM-KS"]


@dataclass
class MicChoice:
    index: int
    name: str
    hostapi: str
    found_snowball: bool


def _sd():
    import sounddevice  # imported late so tests can run without PortAudio
    return sounddevice


def refresh_devices() -> None:
    """Make PortAudio re-scan devices (needed after a mic is unplugged or plugged in)."""
    sd = _sd()
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def list_inputs():
    sd = _sd()
    apis = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            out.append((i, d["name"], apis[d["hostapi"]]["name"]))
    return out


def choose_mic() -> MicChoice | None:
    """Pick the Blue Snowball if present; otherwise the system default input."""
    sd = _sd()
    inputs = list_inputs()
    snow = [x for x in inputs if MIC_HINT in x[1].lower()]
    rank = lambda x: _HOST_ORDER.index(x[2]) if x[2] in _HOST_ORDER else 99
    for cand in sorted(snow, key=rank):
        try:
            sd.check_input_settings(device=cand[0], channels=1,
                                    samplerate=SAMPLE_RATE, dtype="float32")
            return MicChoice(cand[0], cand[1], cand[2], True)
        except Exception:
            continue
    try:
        idx = sd.default.device[0]
        if idx is not None and idx >= 0:
            d = sd.query_devices(idx)
            api = sd.query_hostapis()[d["hostapi"]]["name"]
            return MicChoice(idx, d["name"], api, False)
    except Exception:
        pass
    return None


class LevelMeter:
    """Holds the latest peak and the highest peak since the last reset."""

    def __init__(self):
        self.peak_db = -120.0
        self.max_db = -120.0
        self.clipped = False
        self._lock = threading.Lock()

    def update(self, block: np.ndarray) -> None:
        p = float(np.max(np.abs(block))) if block.size else 0.0
        db = 20 * np.log10(p) if p > 1e-6 else -120.0
        with self._lock:
            self.peak_db = db
            self.max_db = max(self.max_db, db)
            if p >= 0.999:
                self.clipped = True

    def read(self):
        with self._lock:
            return self.peak_db, self.max_db, self.clipped

    def reset(self):
        with self._lock:
            self.max_db = -120.0
            self.clipped = False


class Recorder:
    """Opens the mic once for metering; writes to a file only while recording."""

    def __init__(self, mic: MicChoice):
        self.mic = mic
        self.meter = LevelMeter()
        self._q: queue.Queue = queue.Queue()
        self._stream = None
        self._writer = None
        self._file = None
        self._recording = False
        self._paused = False
        self.path: Path | None = None
        self.meta: dict = {}
        self.frames_written = 0
        self._pause_started = None
        self.last_callback = 0.0
        self.silent_since = None
        self.stream_error = ""

    # ------------------------------------------------------------ stream
    def open(self) -> None:
        sd = _sd()
        self.stream_error = ""
        self.silent_since = None
        self._stream = sd.InputStream(device=self.mic.index, channels=1,
                                      samplerate=SAMPLE_RATE, dtype="float32",
                                      blocksize=1024, callback=self._callback,
                                      finished_callback=self._finished)
        self._stream.start()
        self.last_callback = time.time()

    def _close_stream(self) -> None:
        st, self._stream = self._stream, None
        if st is not None:
            for f in (st.abort, st.close):
                try:
                    f()
                except Exception:
                    pass

    def close(self) -> None:
        if self._recording:
            self.stop()
        self._close_stream()

    def reopen(self, mic: MicChoice) -> None:
        """Switch to a (re)found microphone; a recording in progress continues."""
        self._close_stream()
        self.mic = mic
        self.open()
        if self._recording:
            self.meta.setdefault("microphone_changes", []).append(
                {"at_seconds": round(self.seconds, 2), "microphone": mic.name})

    def _finished(self):
        self.stream_error = self.stream_error or "stream stopped"

    # A live microphone always carries some noise.  No callbacks for 1.5 s,
    # or 1.5 s of exact digital zeros, means the mic is gone.
    LOST_AFTER = 1.5

    def mic_lost(self) -> bool:
        now = time.time()
        if self._stream is None or self.stream_error:
            return True
        try:
            if not self._stream.active:
                return True
        except Exception:
            return True
        if now - self.last_callback > self.LOST_AFTER:
            return True
        return self.silent_since is not None and now - self.silent_since > self.LOST_AFTER

    def _callback(self, indata, frames, time_info, status):
        self.last_callback = time.time()
        block = indata[:, 0].copy()
        if block.size and not np.any(block):
            if self.silent_since is None:
                self.silent_since = self.last_callback
        else:
            self.silent_since = None
        self.meter.update(block)
        if self._recording and not self._paused:
            self._q.put(block)

    # ------------------------------------------------------------ recording
    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def seconds(self) -> float:
        return self.frames_written / SAMPLE_RATE

    def start(self, path: Path, meta: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.meta = dict(meta)
        self.meta.update({
            "file": path.name,
            "started": datetime.now().isoformat(timespec="seconds"),
            "sample_rate": SAMPLE_RATE,
            "encoding": "24-bit PCM WAV, mono",
            "microphone": self.mic.name,
            "microphone_api": self.mic.hostapi,
            "snowball_found": self.mic.found_snowball,
            "pauses": [],
        })
        self.frames_written = 0
        self.meter.reset()
        self._file = sf.SoundFile(str(path), mode="w", samplerate=SAMPLE_RATE,
                                  channels=1, subtype=SUBTYPE, format="WAV")
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._paused = False
        self._recording = True
        self._writer.start()

    def _write_loop(self) -> None:
        while self._recording or not self._q.empty():
            try:
                block = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            self._file.write(block)
            self.frames_written += len(block)

    def pause(self) -> None:
        if self._recording and not self._paused:
            self._paused = True
            self._pause_started = (self.seconds, time.time())

    def resume(self) -> None:
        if self._recording and self._paused:
            at, t0 = self._pause_started
            self.meta["pauses"].append({"at_seconds": round(at, 2),
                                        "length_seconds": round(time.time() - t0, 1)})
            self._paused = False

    def stop(self) -> Path | None:
        if not self._recording:
            return None
        if self._paused:
            self.resume()
        self._recording = False
        self._writer.join(timeout=5)
        self._file.close()
        _, max_db, clipped = self.meter.read()
        self.meta.update({
            "stopped": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": round(self.seconds, 2),
            "peak_dbfs": round(max_db, 1),
            "clipped": clipped,
        })
        side = self.path.with_suffix(".json")
        side.write_text(json.dumps(self.meta, indent=2), encoding="utf-8")
        return self.path
