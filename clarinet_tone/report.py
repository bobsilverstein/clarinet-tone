"""Turn an analysis into a one-page HTML report with comparisons to earlier sessions."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

import numpy as np

from .analysis import MEASURES, history, is_test

INK, MUTED, GRID, BAR, NEG = "#1f2328", "#5f6670", "#e4e7eb", "#2f6fbf", "#c2552d"

EXPLAIN = {
    "cents_abs": "How far each note sits from equal temperament (A = 440 Hz), counting sharp and flat alike.  "
                 "100 cents = one half step.",
    "wobble_cents": "How much the pitch wavers while you hold the note: the standard deviation of the pitch, in cents.",
    "sag_cents": "Pitch change from the first third to the last third of each held note, in cents.",
    "steadiness_pct": "How much the loudness rises and falls while you hold the note: the standard deviation of "
                      "the amplitude divided by its average (coefficient of variation).",
    "brightness": "The average harmonic number, with each harmonic counted in proportion to its strength.  "
                  "1 would mean only the fundamental (a pure tone).",
    "buzz": "Size of the loudness flutter at 20 to 150 times per second, the rate the ear hears as a rattle or buzz, "
            "as a fraction of the average loudness.",
    "hnr_db": "Power in the harmonics versus the hiss between them, as a ratio in decibels.",
}

# How to read each number: which way is better, and what a given size means.
READ = {
    "cents_abs": "<b>Lower is better.</b>  0 means every note sat exactly in tune.  The live pitch meter shows "
                 "green within 10 cents, amber within 25, red beyond.",
    "wobble_cents": "<b>Lower is better.</b>  0 means a perfectly steady pitch.  2 cents means the pitch stayed "
                    "within 2 cents of its average about two-thirds of the time; 10 means it wandered five times as far.",
    "sag_cents": "<b>Closer to 0 is better, on either side.</b>  A negative number means the pitch dropped (went flat) "
                 "as you held the note; a positive number means it rose (went sharp).  So &minus;10 is worse than "
                 "&minus;2, and +5 is as far off as &minus;5.  Drops on some notes and rises on others can cancel "
                 "here; the by-note table shows each note.",
    "steadiness_pct": "<b>Lower is better.</b>  0 % means perfectly even loudness.  5 % means the loudness swayed "
                      "about 5 % above and below its average.",
    "brightness": "<b>Neither higher nor lower is better; your ear decides.</b>  Higher means more energy in the "
                  "upper harmonics, a brighter or edgier sound; lower means a darker, rounder sound.  Low notes "
                  "always read much higher than clarion notes, so a session total depends on which notes the "
                  "exercise holds.  Compare the same note from day to day.",
    "buzz": "<b>Lower is better.</b>  0 means no buzz.  0.010 means the flutter equals 1 % of the average "
            "loudness; 0.020 is twice as much.",
    "hnr_db": "<b>Higher is better (cleaner, less hiss).</b>  Each 3 dB more means the harmonics stand about "
              "twice as far above the hiss; 10 dB more means 10 times as far.",
}

# Which way is better: "lower", "higher", "zero" (closer to 0 either way), or None (no judgment).
BETTER = {key: better for key, _, _, better in MEASURES}
BETTER["sag_cents"] = "zero"
BETTER_TAG = {"lower": "lower is better", "higher": "higher is better", "zero": "closer to 0 is better",
              None: "your ear decides"}


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
            b = BETTER.get(key)
            if b == "lower":
                good = z < 0
            elif b == "higher":
                good = z > 0
            elif b == "zero":
                good = abs(today) < abs(mean)
            else:
                good = None
            word = "" if good is None else (" <span class=good>better</span>" if good else " <span class=bad>worse</span>")
            flag = (f"<div><b>{'▲ higher' if z > 0 else '▼ lower'}</b>{word} <span class=muted>({z:+.1f} SD)</span></div>")
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
    "tuning": "Tuning pattern",
}


def equipment_text(result: dict) -> str:
    """ "Mouthpiece X, ligature Y, barrel Z", or "" when not recorded."""
    eq = result.get("equipment") or {}
    parts = [f"{k} {eq[k]}" for k in ("mouthpiece", "ligature", "barrel") if eq.get(k)]
    t = ", ".join(parts)
    return t[:1].upper() + t[1:]


def _pattern_section(result: dict) -> str:
    """For the tuning pattern: did each target note sound, and how was it."""
    from .config import TUNING_PATTERN
    by = {}
    for n in result["notes"]:
        by.setdefault(n["written"], []).append(n)
    rows = []
    for name in dict.fromkeys(TUNING_PATTERN):          # each note once, in pattern order
        g = by.get(name, [])
        if g:
            c = float(np.median([x["cents"] for x in g]))
            w = float(np.median([x["wobble_cents"] for x in g]))
            rows.append(f"<tr><td>{name}</td><td>yes ({len(g)}×)</td><td class=num>{c:+.1f}</td>"
                        f"<td class=num>{w:.2f}</td></tr>")
        else:
            rows.append(f"<tr><td>{name}</td><td><b>did not sound</b></td><td class=num>–</td><td class=num>–</td></tr>")
    return ("<h2>Pattern check</h2><p class=muted>Pattern: " + ", ".join(TUNING_PATTERN) + "</p>"
            "<table><tr><th>Note</th><th>Sounded</th><th class=num>Pitch, cents</th><th class=num>Wobble, cents</th></tr>"
            + "".join(rows) + "</table>")


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
        ncol = 2 if test else 4
        rows.append(
            f"<tr class=mrow><td class=mname><b>{label}</b></td>"
            f"<td class='num today'>{_fmtu(today, key)}</td>" + cmp + "</tr>"
            f"<tr class=drow><td colspan={ncol}>{EXPLAIN[key]}<br>{READ[key]}</td></tr>")

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
    if result.get("reed_age_days") is not None:
        sub += f" &nbsp;·&nbsp; Reed age {result['reed_age_days']} days"
    eq = equipment_text(result)
    if eq:
        mic += f"<br>Equipment: {html.escape(eq)}"
    pattern = _pattern_section(result) if result.get("exercise") == "tuning" else ""
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
tr.mrow td{{border-bottom:none;padding-bottom:2px}} tr.drow td{{font-size:12pt;color:{MUTED};padding:0 8px 12px 8px}}
tr.drow b{{color:{INK}}} .mname{{white-space:nowrap}}
.good{{color:#1a7f37;font-weight:700}} .bad{{color:#c2552d;font-weight:700}}
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
{pattern}

<h2>By note</h2>
{_bar_chart(bn, 'cents', 'Pitch by written note (negative = flat)', 'cents', True)}
{_bar_chart(bn, 'hnr_db', 'Harmonic-to-noise by written note (higher = cleaner)', 'dB', False)}
{_bar_chart(bn, 'buzz', 'Buzz by written note (lower = smoother)', 'fraction', False)}
<table><tr><th>Note</th><th class=num>Times</th><th class=num>Pitch, cents</th><th class=num>Wobble, cents</th>
<th class=num>Sag, cents</th><th class=num>Unsteadiness, %</th><th class=num>Brightness</th><th class=num>Buzz</th><th class=num>H/N, dB</th></tr>
{note_rows}</table>
<p class=muted>Note names are written pitch for B-flat clarinet.  Values per note are medians over every time you played it.<br>
Pitch: closer to 0 is better; negative = flat, positive = sharp.  Sag: closer to 0 is better; negative = dropped.
Wobble, unsteadiness, and buzz: lower is better.  H/N: higher is better.  Brightness: your ear decides.</p>
</body></html>"""


def build_compare(results: list[dict]) -> str:
    """Side-by-side table of several takes: one column per take, one row per measure."""
    def when(r):
        try:
            return datetime.fromisoformat(r["taken"]).strftime("%m/%d/%Y %I:%M %p")
        except Exception:
            return r.get("taken", "")
    head = "".join(
        f"<th class=num>{html.escape(when(r))}<div class=muted>"
        f"{html.escape(TITLES.get(r.get('exercise'), r.get('exercise_title') or r.get('exercise', '')))}<br>"
        f"Reed {html.escape(r.get('reed', ''))}"
        + (f", {r['reed_age_days']} days" if r.get("reed_age_days") is not None else "")
        + (f"<br>{html.escape(equipment_text(r))}" if equipment_text(r) else "")
        + "</div></th>" for r in results)
    rows = []
    for key, label, unit, better in MEASURES:
        cells = "".join(f"<td class=num>{_fmtu(r.get('summary', {}).get(key), key)}</td>" for r in results)
        rows.append(f"<tr><td><b>{label}</b></td>{cells}</tr>")
    # by note: pitch and brightness for every note any take played
    names = {}
    for r in results:
        for n in r.get("notes", []):
            names[n["written"]] = n["midi_sounding"]
    note_rows = []
    for name in sorted(names, key=names.get):
        cells = ""
        for r in results:
            g = [n for n in r.get("notes", []) if n["written"] == name]
            if g:
                cells += (f"<td class=num>{np.median([n['cents'] for n in g]):+.1f} cents"
                          f"<div class=muted>brightness {np.median([n['brightness'] for n in g]):.2f}</div></td>")
            else:
                cells += "<td class=num>–</td>"
        note_rows.append(f"<tr><td>{name}</td>{cells}</tr>")
    return f"""<!DOCTYPE html>
<html lang=en><head><meta charset=utf-8><title>Comparison of {len(results)} takes</title>
<style>
body{{font-family:"Segoe UI",Arial,sans-serif;font-size:14pt;color:{INK};margin:24px auto;max-width:1200px;padding:0 16px}}
h1{{font-size:22pt;margin:0}} h2{{font-size:16pt;margin-top:28px}}
.muted{{color:{MUTED};font-size:11pt;font-weight:normal}}
table{{border-collapse:collapse;width:100%}} th,td{{border-bottom:1px solid {GRID};padding:6px 8px;vertical-align:top;text-align:left}}
th{{font-size:12pt;font-weight:700}} .num{{text-align:right;white-space:nowrap}}
</style></head><body>
<h1>Comparison of {len(results)} takes</h1>
<p class=muted>Each value is the duration-weighted median over the take's held notes.</p>
<table><tr><th>Measure</th>{head}</tr>{''.join(rows)}</table>
<h2>By note</h2>
<table><tr><th>Note</th>{head}</tr>{''.join(note_rows)}</table>
<p class=muted>Note names are written pitch for B-flat clarinet.</p>
</body></html>"""


def report_path(wav: Path) -> Path:
    return Path(wav).with_name(Path(wav).stem + ".report.html")


def write(result: dict, wav: Path) -> Path:
    p = report_path(wav)
    p.write_text(build(result, Path(wav).parent), encoding="utf-8")
    return p
