"""Turn an analysis into a one-page HTML report with comparisons to earlier sessions."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

import numpy as np

from .analysis import MEASURES, history, is_test

INK, MUTED, GRID, BAR, NEG = "#1f2328", "#5f6670", "#e4e7eb", "#2f6fbf", "#c2552d"

EXPLAIN = {
    "cents_abs": "How far each note sits from equal temperament (A = 440 Hz), ignoring sharp or flat.  100 cents = one half step.",
    "wobble_cents": "How much the pitch wavers while you hold the note: the standard deviation of the pitch, in cents.",
    "sag_cents": "Pitch change from the first third to the last third of the note, in cents.  Negative means the pitch dropped.",
    "steadiness_pct": "Coefficient of variation of the sound amplitude (SD ÷ mean), on raw amplitude, not decibels.",
    "brightness": "The average harmonic number, with each harmonic counted in proportion to its strength.  1 would mean only the fundamental; higher means more energy in the upper harmonics, a brighter sound.",
    "buzz": "Size of the loudness flutter at 20 to 150 times per second, the rate the ear hears as a rattle or buzz, as a fraction of the average loudness.  0 means none.",
    "hnr_db": "Power in the harmonics versus the hiss between them, as a ratio in decibels.  Higher means cleaner.",
}


UNITS = {key: unit for key, _, unit, _ in MEASURES}
UNITS["cents"] = "cents"


def _fmt(v, key):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "–"
    if key == "buzz":
        return f"{v:.3f}"
    if key in ("brightness", "wobble_cents", "sag_cents"):
        return f"{v:.2f}"
    return f"{v:.1f}"


def _fmtu(v, key):
    """Number followed by its unit, e.g. "12.3 cents"."""
    s = _fmt(v, key)
    u = UNITS.get(key, "")
    if s == "–" or u in ("", "fraction"):
        return s
    return f"{s} {u}" if u != "%" else f"{s} %"


def _stats(rows, key):
    v = np.array([r["summary"].get(key, np.nan) for r in rows], float)
    v = v[np.isfinite(v)]
    if not len(v):
        return None
    return float(v.mean()), (float(v.std(ddof=1)) if len(v) > 1 else float("nan")), len(v)


def _compare_cell(today, st, key):
    if st is None:
        return "<td class=num>no earlier data</td>"
    mean, sd, n = st
    txt = f"{_fmt(mean, key)} ± {_fmtu(sd, key)} <span class=muted>(n = {n})</span>" if n > 1 \
        else f"{_fmtu(mean, key)} <span class=muted>(n = 1)</span>"
    flag = ""
    if today is not None and n >= 3 and np.isfinite(sd) and sd > 0:
        z = (today - mean) / sd
        if abs(z) >= 2:
            flag = f" <b>{'▲ higher' if z > 0 else '▼ lower'}</b> <span class=muted>({z:+.1f} SD)</span>"
    return f"<td class=num>{txt}{flag}</td>"


def _by_note(notes):
    groups = {}
    for n in notes:
        groups.setdefault(n["midi_sounding"], []).append(n)
    out = []
    for m in sorted(groups):
        g = groups[m]
        row = {"written": g[0]["written"], "count": len(g)}
        for key in ("cents", "wobble_cents", "sag_cents", "steadiness_pct", "brightness", "buzz", "hnr_db"):
            v = np.array([x[key] for x in g], float)
            v = v[np.isfinite(v)]
            row[key] = float(np.median(v)) if len(v) else float("nan")
        out.append(row)
    return out


def _nice_step(raw: float) -> float:
    if raw <= 0:
        return 1.0
    e = 10 ** np.floor(np.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * e:
            return float(m * e)
    return float(10 * e)


TITLES = {
    "long-tone-chalumeau": "Long tones, chalumeau",
    "long-tone-clarion": "Long tones, clarion",
    "long-tone": "Long tones",
    "legato": "Legato warm-up",
    "register": "Register key / embouchure",
}


def _bar_chart(rows, key, title, unit, signed):
    """Single-series vertical bar chart, one bar per written note, low to high."""
    if not rows:
        return ""
    W, H, L, R, T, B = 900, 260, 52, 10, 30, 46
    vals = np.array([r[key] for r in rows], float)
    ok = np.isfinite(vals)
    if not ok.any():
        return ""
    lo = min(0.0, float(np.nanmin(vals))) if signed else 0.0
    hi = max(0.0, float(np.nanmax(vals)))
    if hi == lo:
        hi = lo + 1
    step_t = _nice_step((hi - lo) / 4)
    lo = np.floor(lo / step_t) * step_t
    hi = np.ceil(hi / step_t) * step_t
    if hi == lo:
        hi = lo + step_t
    dec = max(0, -int(np.floor(np.log10(step_t)))) if step_t < 1 else 0

    def y(v):
        return T + (hi - v) / (hi - lo) * (H - T - B)
    n = len(rows)
    slot = (W - L - R) / n
    bw = max(2.0, min(26.0, slot - 2))
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}" class=chart>',
             f'<text x="{L}" y="18" class=ct>{html.escape(title)}</text>']
    # grid and axis labels
    ticks = np.arange(lo, hi + step_t / 2, step_t)
    for t in ticks:
        parts.append(f'<line x1="{L}" x2="{W-R}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{L-6}" y="{y(t)+4:.1f}" text-anchor="end" class=ax>{t:.{dec}f}</text>')
    parts.append(f'<line x1="{L}" x2="{W-R}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="{MUTED}" stroke-width="1"/>')
    parts.append(f'<text x="12" y="{(T+H-B)/2:.0f}" transform="rotate(-90 12 {(T+H-B)/2:.0f})" text-anchor="middle" class=ax>{html.escape(unit)}</text>')
    step = max(1, int(np.ceil(n / 30)))
    for i, r in enumerate(rows):
        v = r[key]
        cx = L + slot * (i + 0.5)
        if np.isfinite(v):
            y0, y1 = sorted((y(0), y(v)))
            col = NEG if (signed and v < 0) else BAR
            parts.append(
                f'<g class=bar><rect x="{cx-slot/2:.1f}" y="{T}" width="{slot:.1f}" height="{H-T-B}" fill="transparent"/>'
                f'<rect x="{cx-bw/2:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{max(y1-y0, 1):.1f}" rx="3" fill="{col}"/>'
                f'<title>{html.escape(r["written"])}: {v:.2f} {html.escape(unit)} (played {r["count"]}×)</title></g>')
        if i % step == 0:
            parts.append(f'<text x="{cx:.1f}" y="{H-B+16}" text-anchor="middle" class=ax>{html.escape(r["written"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def build(result: dict, folder: Path) -> str:
    test = is_test(result.get("exercise", ""))
    past = [] if test else [r for r in history(folder)
            if r.get("exercise") == result["exercise"] and r.get("file") != result["file"]
            and r.get("taken", "") < result.get("taken", "~")]
    same = [r for r in past if r.get("reed") == result["reed"]][-5:]
    alls = past[-5:]
    s = result["summary"]
    try:
        when = datetime.fromisoformat(result["taken"]).strftime("%A, %B %-d, %Y, %-I:%M %p")
    except Exception:
        try:
            when = datetime.fromisoformat(result["taken"]).strftime("%A, %B %d, %Y, %I:%M %p")
        except Exception:
            when = result.get("taken", "")

    rows = []
    for key, label, unit, better in MEASURES:
        today = s.get(key)
        cmp = "" if test else (_compare_cell(today, _stats(same, key), key)
                               + _compare_cell(today, _stats(alls, key), key))
        rows.append(
            f"<tr><td><b>{label}</b><div class=muted>{EXPLAIN[key]}</div></td>"
            f"<td class='num today'>{_fmtu(today, key)}</td>" + cmp + "</tr>")

    bn = _by_note(result["notes"])
    note_rows = "".join(
        f"<tr><td>{html.escape(r['written'])}</td><td class=num>{r['count']}</td>"
        f"<td class=num>{r['cents']:+.1f}</td><td class=num>{_fmt(r['wobble_cents'],'wobble_cents')}</td>"
        f"<td class=num>{_fmt(r['sag_cents'],'sag_cents')}</td><td class=num>{_fmt(r['steadiness_pct'],'steadiness_pct')}</td>"
        f"<td class=num>{_fmt(r['brightness'],'brightness')}</td><td class=num>{_fmt(r['buzz'],'buzz')}</td>"
        f"<td class=num>{_fmt(r['hnr_db'],'hnr_db')}</td></tr>" for r in bn)

    if test:
        desc = result.get("test_description") or result["file"].rsplit("_", 1)[-1].removesuffix(".wav")
        head = html.escape(f"Test: {desc}")
    else:
        head = html.escape(TITLES.get(result["exercise"], result.get("exercise_title") or result["exercise"]))
    sub = (f"{when} &nbsp;·&nbsp; Reed {html.escape(result['reed'])} &nbsp;·&nbsp; "
           f"{int(result['duration_s'] // 60)}:{int(result['duration_s'] % 60):02d} long &nbsp;·&nbsp; "
           f"{len(result['notes'])} held notes found")
    mic = f" &nbsp;·&nbsp; {html.escape(result['microphone'])}" if result.get("microphone") else ""
    ha = result.get("hearing_aids")
    mic += " &nbsp;·&nbsp; Hearing aids " + ("on" if ha else "off" if ha is False else "not recorded")
    if test:
        intro = ("<p class=note>This is a test take.  Each value is the duration-weighted median over all held notes.  "
                 "Test takes never enter your exercise history or comparisons.</p>")
        cols = "<tr><th>Measure</th><th class=num>Today</th></tr>"
    else:
        intro = ("<p class=note>Each value is the duration-weighted median over all held notes.  The two comparison columns give the\n"
                 "mean ± SD of the last five sessions of this exercise: first on this reed only (aging), then on all reeds (ranking).\n"
                 "A mark appears when today falls 2 or more SD from that mean, with at least three earlier sessions.</p>")
        cols = ("<tr><th>Measure</th><th class=num>Today</th><th class=num>This reed, last 5</th>"
                "<th class=num>All reeds, last 5</th></tr>")

    return f"""<!DOCTYPE html>
<html lang=en><head><meta charset=utf-8><title>{head} – {html.escape(result['file'])}</title>
<style>
body{{font-family:"Segoe UI",Arial,sans-serif;font-size:14pt;color:{INK};margin:24px auto;max-width:1000px;padding:0 16px}}
h1{{font-size:22pt;margin:0}} h2{{font-size:16pt;margin-top:28px}}
.muted{{color:{MUTED};font-size:11pt;font-weight:normal}}
table{{border-collapse:collapse;width:100%}} th,td{{border-bottom:1px solid {GRID};padding:6px 8px;vertical-align:top;text-align:left}}
th{{font-size:12pt;color:{MUTED};font-weight:600}} .num{{text-align:right;white-space:nowrap}}
.today{{font-weight:700;font-size:15pt}}
.chart{{width:100%;height:auto;margin-top:8px}} .ct{{font-size:15px;font-weight:600;fill:{INK}}} .ax{{font-size:12px;fill:{MUTED}}}
.bar:hover rect+rect{{opacity:.75}}
.note{{background:#f4f6f8;padding:10px 14px;border-radius:6px;font-size:12pt}}
</style></head><body>
<h1>{head}</h1>
<div class=muted>{sub}{mic}<br>{html.escape(result['file'])}</div>

<h2>Summary</h2>
{intro}
<table>{cols}
{''.join(rows)}</table>
<p class=muted>Average pitch today: {s.get('cents_signed', float('nan')):+.1f} cents (negative = flat).</p>

<h2>By note</h2>
{_bar_chart(bn, 'cents', 'Pitch by written note (negative = flat)', 'cents', True)}
{_bar_chart(bn, 'hnr_db', 'Harmonic-to-noise by written note (higher = cleaner)', 'dB', False)}
{_bar_chart(bn, 'buzz', 'Buzz by written note (lower = smoother)', 'fraction', False)}
<table><tr><th>Note</th><th class=num>Times</th><th class=num>Pitch, cents</th><th class=num>Wobble, cents</th>
<th class=num>Sag, cents</th><th class=num>Unsteadiness, %</th><th class=num>Brightness</th><th class=num>Buzz</th><th class=num>H/N, dB</th></tr>
{note_rows}</table>
<p class=muted>Note names are written pitch for B-flat clarinet.  Values per note are medians over every time you played it.</p>
</body></html>"""


def report_path(wav: Path) -> Path:
    return Path(wav).with_name(Path(wav).stem + ".report.html")


def write(result: dict, wav: Path) -> Path:
    p = report_path(wav)
    p.write_text(build(result, Path(wav).parent), encoding="utf-8")
    return p
