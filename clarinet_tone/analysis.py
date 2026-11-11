"""Measure the tone of one recording, note by note.

Every measure is dimensionless:
  pitch      cents from equal temperament (A = 440 Hz); cents are a frequency ratio
  wobble     SD of pitch in cents while the note is held
  sag        pitch change in cents from the first third to the last third of the note
  steadiness coefficient of variation of sound amplitude (not decibels), %
  brightness spectral centroid divided by the note's fundamental (1 = pure fundamental)
  buzz       loudness flutter at 20-150 Hz as a fraction of the average loudness (roughness)
  air noise  harmonic-to-noise power ratio, expressed in dB (higher is cleaner)

Only numpy is used, so the packaged program stays small.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

VERSION = 2                         # 2: wobble and sag in cents; hearing aids
FMIN, FMAX = 140.0, 1900.0          # clarinet sounding range, with margin
HOP_S = 0.010                       # 10 ms between pitch frames
WIN = 2048                          # pitch window at 48 kHz (43 ms)
YIN_THRESHOLD = 0.15
FLATS = ["C", "D♭", "D", "E♭", "E", "F", "G♭", "G", "A♭", "A", "B♭", "B"]

# Held while a recording file is open for reading, so "Discard" can wait for it
# (Windows cannot delete a file another thread has open).
READ_LOCK = threading.Lock()

MEASURES = [  # key, label, unit, which direction is better (None = closer to zero / no judgment)
    ("cents_abs", "Pitch error", "cents", "lower"),
    ("wobble_cents", "Wobble", "cents", "lower"),
    ("sag_cents", "Sag", "cents", None),
    ("steadiness_pct", "Loudness unsteadiness", "%", "lower"),
    ("brightness", "Brightness", "× fundamental", None),
    ("buzz", "Buzz", "fraction", "lower"),
    ("hnr_db", "Harmonic-to-noise", "dB", "higher"),
]


def written_name(midi_sounding: int) -> str:
    """B-flat clarinet: written pitch is a whole step above sounding pitch."""
    m = midi_sounding + 2
    return f"{FLATS[m % 12]}{m // 12 - 1}"


# ----------------------------------------------------------------- pitch (YIN)

def _yin_block(frames: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """YIN pitch for a block of frames (n x WIN).  Returns f0 (Hz, nan if none) and aperiodicity."""
    n, w = frames.shape
    tmax = int(sr / FMIN) + 2
    tmin = max(2, int(sr / FMAX))
    half = w - tmax
    x = frames
    # difference function d(tau) = sum_{j<half} (x_j - x_{j+tau})^2, via FFT
    nfft = 1 << int(np.ceil(np.log2(w + half)))
    X = np.fft.rfft(x, nfft)
    A = np.fft.rfft(x[:, :half], nfft)
    r = np.fft.irfft(np.conj(A) * X, nfft)[:, :tmax]                 # sum x_j x_{j+tau}
    sq = np.cumsum(np.concatenate([np.zeros((n, 1)), x * x], axis=1), axis=1)
    e0 = sq[:, half][:, None]                                           # sum_{j<half} x_j^2
    taus = np.arange(tmax)
    et = sq[:, taus + half] - sq[:, taus]                               # sum x_{j+tau}^2
    d = e0 + et - 2 * r
    d[:, 0] = 0
    cs = np.cumsum(d[:, 1:], axis=1)
    cmnd = np.ones_like(d)
    cmnd[:, 1:] = d[:, 1:] * np.arange(1, tmax) / np.maximum(cs, 1e-12)
    f0 = np.full(n, np.nan)
    ap = np.ones(n)
    sub = cmnd[:, tmin:tmax - 1]
    below = sub < YIN_THRESHOLD
    for i in range(n):
        idx = np.flatnonzero(below[i])
        if idx.size:
            t = idx[0]
            while t + 1 < sub.shape[1] and sub[i, t + 1] < sub[i, t]:
                t += 1
        else:
            t = int(np.argmin(sub[i]))
        tau = t + tmin
        ap[i] = cmnd[i, tau]
        a, b, c = cmnd[i, tau - 1], cmnd[i, tau], cmnd[i, tau + 1]
        den = a - 2 * b + c
        shift = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
        f0[i] = sr / (tau + float(np.clip(shift, -1, 1)))
    return f0, ap


def track_pitch(y: np.ndarray, sr: int, progress=None):
    hop = int(round(HOP_S * sr))
    n = max(0, (len(y) - WIN) // hop + 1)
    f0 = np.full(n, np.nan)
    ap = np.ones(n)
    rms = np.zeros(n)
    block = 1500
    for s in range(0, n, block):
        e = min(n, s + block)
        idx = np.arange(s, e)[:, None] * hop + np.arange(WIN)[None, :]
        fr = y[idx]
        rms[s:e] = np.sqrt(np.mean(fr * fr, axis=1))
        f0[s:e], ap[s:e] = _yin_block(fr, sr)
        if progress:
            progress(e / max(n, 1))
    return f0, ap, rms, hop


# ----------------------------------------------------------------- notes

def split_notes(f0, ap, rms, hop, sr, min_dur):
    """Group frames into held notes.  A frame stays with the current note while it is
    within 0.8 semitone of it, so a note played 40 cents off does not split in two."""
    db = 20 * np.log10(rms + 1e-12)
    loud = db > (np.percentile(db, 99) - 35)
    voiced = (ap < 0.25) & loud & np.isfinite(f0)
    mc = np.full(len(f0), np.nan)
    mc[voiced] = 69 + 12 * np.log2(f0[voiced] / 440.0)
    notes = []
    i, n = 0, len(mc)
    while i < n:
        if np.isnan(mc[i]):
            i += 1
            continue
        m = mc[i]
        j, gap = i, 0
        while j + 1 < n:
            v = mc[j + 1]
            if np.isfinite(v) and abs(v - m) < 0.8:
                j += 1
                gap = 0
                if j - i < 20:
                    m = float(np.nanmedian(mc[i:j + 1]))
            elif gap < 5:
                j += 1
                gap += 1
            else:
                break
        j -= gap
        dur = (j - i + 1) * hop / sr
        if dur >= min_dur:
            notes.append((i, j + 1, int(round(float(np.nanmedian(mc[i:j + 1]))))))
        i = j + 1
    return notes


# ----------------------------------------------------------------- per-note measures

def _spectrum_measures(seg: np.ndarray, sr: int, f0: float):
    """Average power spectrum of the steady part; brightness and harmonic-to-noise ratio."""
    nfft = 8192
    if len(seg) < nfft:
        seg = np.pad(seg, (0, nfft - len(seg)))
    win = np.hanning(nfft)
    step = nfft // 2
    P = np.zeros(nfft // 2 + 1)
    k = 0
    for s in range(0, len(seg) - nfft + 1, step):
        P += np.abs(np.fft.rfft(seg[s:s + nfft] * win)) ** 2
        k += 1
    P /= max(k, 1)
    freqs = np.fft.rfftfreq(nfft, 1 / sr)
    top = min(12000.0, sr / 2 - 100)
    harm_power, amps = 0.0, []
    mask = np.zeros(len(freqs), bool)
    h = 1
    while h * f0 < top:
        band = np.abs(freqs - h * f0) <= max(3 * sr / nfft, 0.03 * h * f0)
        mask |= band
        p = P[band].sum()
        harm_power += p
        amps.append(np.sqrt(p))
        h += 1
    rng = (freqs >= 0.5 * f0) & (freqs <= top)
    noise = P[rng & ~mask].sum()
    amps = np.array(amps)
    brightness = float(np.sum(np.arange(1, len(amps) + 1) * amps) / max(amps.sum(), 1e-12))
    hnr_db = float(10 * np.log10(max(harm_power, 1e-20) / max(noise, 1e-20)))
    return brightness, hnr_db


def _buzz(seg: np.ndarray, sr: int, f0: float) -> float:
    """Roughness: size of the loudness flutter at 20-150 Hz (the rate heard as a rattle or buzz),
    as a fraction of the average loudness (a modulation index; 0 = none).
    The envelope is a moving RMS over a whole number of periods (at least 3 ms), so the
    note's own waveform does not leak into the measure."""
    period = sr / f0
    win = int(round(np.ceil(0.003 * f0) * period))
    hop = sr // 1000                                    # 1 ms envelope
    if len(seg) < win + 512 * hop:
        return float("nan")
    c = np.concatenate([[0.0], np.cumsum(seg.astype(np.float64) ** 2)])
    starts = np.arange(0, len(seg) - win, hop)
    env = np.sqrt((c[starts + win] - c[starts]) / win)
    n = len(env)
    mean = env.mean()
    if mean <= 0:
        return float("nan")
    F = np.fft.rfft(env - mean)
    fr = np.fft.rfftfreq(n, 1 / 1000)
    F[(fr < 20) | (fr > 150)] = 0
    band = np.fft.irfft(F, n)
    return float(np.std(band) / mean)


def measure_note(y, sr, f0, rms, hop, a, b, m):
    L = b - a
    mid = slice(a + int(0.2 * L), a + int(0.8 * L))
    f = f0[mid]
    f = f[np.isfinite(f)]
    target = 440.0 * 2 ** ((m - 69) / 12)
    if len(f) < 5:
        return None
    cents = 1200 * np.log2(f / target)
    ok = np.abs(cents - np.median(cents)) < 60          # drop octave slips
    f, cents = f[ok], cents[ok]
    if len(f) < 5:
        return None
    full = f0[a + int(0.1 * L): a + int(0.95 * L)]
    full = full[np.isfinite(full)]
    full = full[np.abs(1200 * np.log2(full / target) - np.median(cents)) < 60]
    thirds = np.array_split(full, 3) if len(full) >= 9 else [f, f, f]
    sag = 1200 * np.log2(np.median(thirds[2]) / np.median(thirds[0]))
    amp = rms[mid]
    s0, s1 = mid.start * hop, mid.stop * hop + WIN
    seg = y[s0:s1]
    fm = float(np.median(f))
    bright, hnr = _spectrum_measures(seg, sr, fm)
    return {
        "start_s": round(a * hop / sr, 2),
        "dur_s": round(L * hop / sr, 2),
        "written": written_name(m),
        "midi_sounding": m,
        "freq_hz": round(fm, 2),
        "cents": round(float(np.median(cents)), 1),
        "cents_abs": round(abs(float(np.median(cents))), 1),
        "wobble_cents": round(float(np.std(cents)), 2),
        "sag_cents": round(float(sag), 2),
        "steadiness_pct": round(float(100 * np.std(amp) / max(np.mean(amp), 1e-12)), 2),
        "brightness": round(bright, 3),
        "buzz": round(_buzz(seg, sr, fm), 3),
        "hnr_db": round(hnr, 1),
        "level_dbfs": round(float(20 * np.log10(np.mean(amp) + 1e-12)), 1),
    }


# ----------------------------------------------------------------- live

LIVE_SAMPLES = 16384        # about 1/3 second at 48 kHz


def live_brightness(x: np.ndarray, sr: int, floor_db: float = -45.0):
    """Brightness of the sound right now.  Returns (written note, cents, brightness)
    or None when no steady note is sounding."""
    if len(x) < LIVE_SAMPLES:
        return None
    x = x[-LIVE_SAMPLES:].astype(np.float64)
    if 20 * np.log10(np.sqrt(np.mean(x * x)) + 1e-12) < floor_db:
        return None
    # pitch from three frames across the window; they must agree (a steady note)
    starts = np.linspace(0, len(x) - WIN, 3).astype(int)
    f, ap = _yin_block(np.stack([x[s:s + WIN] for s in starts]), sr)
    if not (np.all(np.isfinite(f)) and np.all(ap < 0.25)):
        return None
    if np.ptp(1200 * np.log2(f / np.median(f))) > 40:
        return None
    f0 = float(np.median(f))
    if not FMIN <= f0 <= FMAX:
        return None
    midi = 69 + 12 * np.log2(f0 / 440.0)
    m = int(round(midi))
    bright, _ = _spectrum_measures(x, sr, f0)
    return written_name(m), round(100 * (midi - m), 1), round(bright, 2)


def usual_brightness(folder: Path, sessions: int = 10) -> dict:
    """Median brightness per written note over the last few exercise sessions."""
    by = {}
    for r in history(folder)[-sessions:]:
        for n in r.get("notes", []):
            v = n.get("brightness")
            if v is not None and np.isfinite(v):
                by.setdefault(n["written"], []).append(v)
    return {k: round(float(np.median(v)), 2) for k, v in by.items()}


# ----------------------------------------------------------------- whole take

def exercise_of(wav: Path, meta: dict) -> str:
    if wav.parent.name.lower() == "tests" and not is_test(meta.get("exercise", "")):
        return "test"           # takes kept in Recordings\Tests are tests, whatever they were recorded as
    if meta.get("exercise"):
        return meta["exercise"]
    name = wav.stem.lower()
    for key in ("long-tone-chalumeau", "long-tone-clarion", "long-tone", "legato", "register", "tuning"):
        if key in name:
            return key
    return "other"


def reed_of(wav: Path, meta: dict) -> str:
    r = meta.get("reed")
    if isinstance(r, dict) and r.get("label"):
        return r["label"]
    m = re.search(r"reed-(\d{4})[-_](\d)", wav.stem)
    return f"{m.group(1)}-{m.group(2)}" if m else "unknown"


# Hearing aids for takes made before the program asked (from Bob's log).
HEARING_AIDS_LOG = {"2026-11-05": False, "2026-11-06": False}


def hearing_aids_of(wav: Path, meta: dict, taken: str):
    if isinstance(meta.get("hearing_aids"), bool):
        return meta["hearing_aids"]
    return HEARING_AIDS_LOG.get(taken[:10])


def is_test(exercise: str) -> bool:
    return exercise == "test" or exercise.startswith("test-")


def taken_at(wav: Path, meta: dict) -> str:
    if meta.get("started"):
        return meta["started"]
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})", wav.stem)
    return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:00" if m else ""


def summarize(notes: list[dict]) -> dict:
    out = {}
    if not notes:
        return out
    w = np.array([n["dur_s"] for n in notes])
    for key, *_ in MEASURES:
        v = np.array([n[key] for n in notes], float)
        good = np.isfinite(v)
        if good.any():
            # duration-weighted median
            order = np.argsort(v[good])
            vv, ww = v[good][order], w[good][order]
            c = np.cumsum(ww)
            out[key] = round(float(vv[np.searchsorted(c, c[-1] / 2)]), 3)
    out["cents_signed"] = round(float(np.median([n["cents"] for n in notes])), 1)
    return out


def analyze(wav: Path, progress=None) -> dict:
    wav = Path(wav)
    meta = {}
    side = wav.with_suffix(".json")
    with READ_LOCK:
        if side.exists():
            try:
                meta = json.loads(side.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        y, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    f0, ap, rms, hop = track_pitch(y, sr, progress)
    ex = exercise_of(wav, meta)
    taken = taken_at(wav, meta)
    min_dur = 1.0 if ex.startswith("long-tone") else 0.3
    notes = []
    for a, b, m in split_notes(f0, ap, rms, hop, sr, min_dur):
        r = measure_note(y, sr, f0, rms, hop, a, b, m)
        if r:
            notes.append(r)
    return {
        "version": VERSION,
        "file": wav.name,
        "taken": taken,
        "exercise": ex,
        "exercise_title": meta.get("exercise_title", ex),
        "reed": reed_of(wav, meta),
        "duration_s": round(len(y) / sr, 1),
        "microphone": meta.get("microphone", ""),
        "hearing_aids": hearing_aids_of(wav, meta, taken),
        "test_description": meta.get("test_description", ""),
        "reed_age_days": meta.get("reed_age_days"),
        "equipment": meta.get("equipment") or {},
        "notes": notes,
        "summary": summarize(notes),
    }


def analysis_path(wav: Path) -> Path:
    return Path(wav).with_name(Path(wav).stem + ".analysis.json")


def save(result: dict, wav: Path) -> Path:
    p = analysis_path(wav)
    p.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return p


def history(folder: Path) -> list[dict]:
    """Earlier exercise sessions in this folder (test takes never count)."""
    out = []
    for p in sorted(Path(folder).glob("*.analysis.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not is_test(r.get("exercise", "")):
            out.append(r)
    return sorted(out, key=lambda r: r.get("taken", ""))


def is_stale(wav: Path) -> bool:
    """True when the recording has no analysis, or one made by an older version."""
    p = analysis_path(wav)
    if not p.exists():
        return True
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("version", 0) < VERSION
    except Exception:
        return True
