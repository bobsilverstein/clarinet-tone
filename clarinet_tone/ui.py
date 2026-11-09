"""Main window."""
import os
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QDate, QObject, Signal
import threading
from PySide6.QtGui import QColor, QFont, QIcon, QPainter
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QProgressDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from . import config as C
from . import updater as U
from . import analysis as AN
from . import report as RP


class _Relay(QObject):
    done = Signal(str, str)      # wav path, error text ("" if fine)
    progress = Signal(str)


def stale_recordings(folder: Path, skip: Path | None = None) -> list[Path]:
    """Recordings in folder (and its Tests subfolder) with no report or an out-of-date analysis."""
    out = []
    for d in (folder, folder / "Tests"):
        if d.is_dir():
            out += [w for w in sorted(d.glob("*.wav"))
                    if w != skip and (AN.is_stale(w) or not RP.report_path(w).exists())]
    return out


def remake(wavs: list[Path], note=None) -> None:
    """Measure all first, then write reports oldest first, so each compares with the ones before it."""
    results = []
    for i, w in enumerate(wavs, 1):
        if note:
            note(f"Measuring {i} of {len(wavs)}: {w.name}")
        res = AN.analyze(w)
        AN.save(res, w)
        results.append((res.get("taken", ""), w, res))
    for _, w, res in sorted(results, key=lambda t: t[0]):
        RP.write(res, w)


def make_report(wav: Path) -> dict:
    """Measure one recording and write its analysis and report next to it.
    Older sessions measured by an earlier version are measured again first,
    so the comparisons use the same measures."""
    base = wav.parent.parent if wav.parent.name.lower() == "tests" else wav.parent
    with _REPORT_LOCK:          # one report at a time, even if two takes are saved close together
        remake(stale_recordings(base, skip=wav))
        res = AN.analyze(wav)
        AN.save(res, wav)
        RP.write(res, wav)
    return res


_REPORT_LOCK = threading.Lock()


def open_file(p: Path):
    if os.name == "nt":
        os.startfile(str(p))
    else:
        subprocess.Popen(["xdg-open", str(p)])


class ReportsDialog(QDialog):
    """List past reports, newest first; make any that are missing."""
    def __init__(self, parent, folder: Path):
        super().__init__(parent)
        self.setWindowTitle("Reports")
        self.folder = folder
        self.resize(760, 520)
        v = QVBoxLayout(self)
        self.lst = QListWidget()
        self.lst.itemDoubleClicked.connect(lambda it: open_file(Path(it.data(Qt.UserRole))))
        v.addWidget(QLabel("Double-click a report to open it."))
        v.addWidget(self.lst, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        h = QHBoxLayout()
        self.btn_make = QPushButton("Make missing reports")
        self.btn_make.clicked.connect(self.make_missing)
        h.addWidget(self.btn_make)
        h.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        h.addWidget(close)
        v.addLayout(h)
        self.fill()

    def missing(self):
        return stale_recordings(self.folder)

    def fill(self):
        self.lst.clear()
        reports = list(self.folder.glob("*.report.html")) + list((self.folder / "Tests").glob("*.report.html"))
        for p in sorted(reports, key=lambda p: p.name, reverse=True):
            tag = "   (test)" if p.parent.name.lower() == "tests" else ""
            it = QListWidgetItem(p.name.replace(".report.html", "") + tag)
            it.setData(Qt.UserRole, str(p))
            self.lst.addItem(it)
        m = self.missing()
        self.btn_make.setEnabled(bool(m))
        self.note.setText(f"{len(m)} recording(s) need a new or updated report." if m
                          else "Every recording has an up-to-date report.")

    def make_missing(self):
        todo = self.missing()
        if not todo:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        def note(text):
            self.note.setText(text)
            QApplication.processEvents()
        try:
            remake(todo, note)
        except Exception as e:
            QMessageBox.warning(self, "Reports", f"Could not finish:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()
        self.fill()
from .recorder import Recorder, choose_mic, refresh_devices


class BrightnessChart(QWidget):
    """Scrolling chart of brightness over the last SPAN seconds."""
    SPAN = 30.0

    def __init__(self):
        super().__init__()
        self.points = []            # (time, brightness or None)
        self.usual = None
        self.setMinimumHeight(260)

    def add(self, t: float, v):
        self.points.append((t, v))
        while self.points and self.points[0][0] < t - self.SPAN:
            self.points.pop(0)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        L, R, T, B = 50, 10, 10, 26
        p.fillRect(0, 0, W, H, QColor("white"))
        vals = [v for _, v in self.points if v is not None]
        if self.usual is not None:
            vals.append(self.usual)
        hi = max(vals) if vals else 4.0
        lo = min(vals) if vals else 1.0
        span = max(hi - lo, 0.5)
        step = RP._nice_step(span / 4)
        import math
        lo = max(1.0, math.floor(lo / step) * step)
        hi = max(math.ceil(hi / step) * step, lo + step)
        y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
        now = self.points[-1][0] if self.points else 0.0
        x = lambda tt: L + (tt - (now - self.SPAN)) / self.SPAN * (W - L - R)
        p.setPen(QColor("#e4e7eb"))
        f = p.font(); f.setPointSize(10); p.setFont(f)
        v = lo
        while v <= hi + 1e-9:
            p.setPen(QColor("#e4e7eb")); p.drawLine(L, int(y(v)), W - R, int(y(v)))
            p.setPen(QColor("#5f6670")); p.drawText(4, int(y(v)) + 4, f"{v:g}")
            v += step
        for s in range(0, int(self.SPAN) + 1, 5):
            xx = x(now - s)
            p.setPen(QColor("#5f6670"))
            p.drawText(int(xx) - 14, H - 6, f"-{s}s" if s else "now")
        if self.usual is not None:
            from PySide6.QtGui import QPen
            pen = QPen(QColor("#c2552d")); pen.setStyle(Qt.DashLine); pen.setWidth(2)
            p.setPen(pen)
            p.drawLine(L, int(y(self.usual)), W - R, int(y(self.usual)))
        from PySide6.QtGui import QPen
        pen = QPen(QColor("#2f6fbf")); pen.setWidth(3)
        p.setPen(pen)
        prev = None
        for tt, v in self.points:
            if v is None:
                prev = None
                continue
            pt = (int(x(tt)), int(y(v)))
            if prev:
                p.drawLine(prev[0], prev[1], pt[0], pt[1])
            else:
                p.drawPoint(pt[0], pt[1])
            prev = pt
        p.end()


class LiveBrightness(QDialog):
    """Shows brightness of the note you are playing, about 10 times a second."""

    def __init__(self, parent, get_rec, folder: Path):
        super().__init__(parent)
        self.setWindowTitle("Live brightness")
        self.get_rec = get_rec
        self.usual = AN.usual_brightness(folder)
        self.recent = []
        self.t0 = time.time()
        self.resize(820, 520)
        v = QVBoxLayout(self)
        self.big = QLabel("–")
        self.big.setAlignment(Qt.AlignCenter)
        bf = QFont(self.font()); bf.setPointSize(48); bf.setBold(True)
        self.big.setFont(bf)
        v.addWidget(self.big)
        self.note = QLabel("Play a note.")
        self.note.setAlignment(Qt.AlignCenter)
        nf = QFont(self.font()); nf.setPointSize(18)
        self.note.setFont(nf)
        v.addWidget(self.note)
        self.usual_label = QLabel("")
        self.usual_label.setAlignment(Qt.AlignCenter)
        self.usual_label.setStyleSheet("color:#c2552d")
        v.addWidget(self.usual_label)
        self.chart = BrightnessChart()
        v.addWidget(self.chart, 1)
        hint = QLabel("Blue line: brightness over the last 30 seconds.  Dashed line: your usual brightness "
                      "on this note (median of your last 10 sessions).  Higher means brighter.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#5f6670")
        v.addWidget(hint)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

    def tick(self):
        rec = self.get_rec()
        now = time.time() - self.t0
        if rec is None:
            self.note.setText("No microphone.")
            self.chart.add(now, None)
            return
        try:
            r = AN.live_brightness(rec.recent(AN.LIVE_SAMPLES), C.SAMPLE_RATE)
        except Exception:
            r = None
        if r is None:
            self.recent.clear()
            self.chart.add(now, None)
            self.big.setStyleSheet("color:#9aa0a6")
            return
        name, cents, b = r
        self.recent = (self.recent + [(name, b)])[-3:]
        same = [x for n, x in self.recent if n == name]
        shown = sorted(same)[len(same) // 2]
        self.big.setText(f"{shown:.2f}")
        self.big.setStyleSheet("color:#1f2328")
        self.note.setText(f"Written {name}   {cents:+.0f} cents")
        u = self.usual.get(name)
        self.chart.usual = u
        self.usual_label.setText(f"Your usual on {name}: {u:.2f}" if u is not None else "")
        self.chart.add(now, b)

    def done(self, r):
        self.timer.stop()
        super().done(r)

FONT_PT = 14


class LevelBar(QWidget):
    """Horizontal level meter, -60 to 0 dBFS, with yellow and red zones."""

    LO = -60.0

    def __init__(self, yellow: float, red: float):
        super().__init__()
        self.yellow, self.red = yellow, red
        self.level = self.LO
        self.hold = self.LO
        self.setMinimumHeight(44)

    def set_levels(self, level: float, hold: float) -> None:
        self.level, self.hold = level, hold
        self.update()

    def _x(self, db: float) -> int:
        db = max(self.LO, min(0.0, db))
        return int((db - self.LO) / -self.LO * self.width())

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#2b2b2b"))
        xy, xr, xl = self._x(self.yellow), self._x(self.red), self._x(self.level)
        p.fillRect(0, 0, min(xl, xy), h, QColor("#3cb44b"))
        if xl > xy:
            p.fillRect(xy, 0, min(xl, xr) - xy, h, QColor("#f2c12e"))
        if xl > xr:
            p.fillRect(xr, 0, xl - xr, h, QColor("#e03c31"))
        # peak hold line
        xh = self._x(self.hold)
        p.fillRect(max(0, xh - 2), 0, 3, h, QColor("white"))
        # zone marks
        p.setPen(QColor("#888"))
        for db in (-48, -36, -24, -12, -6, -3):
            x = self._x(db)
            p.drawLine(x, h - 8, x, h)
        p.end()


class ReedDialog(QDialog):
    def __init__(self, parent=None, reed: C.Reed | None = None):
        super().__init__(parent)
        self.setWindowTitle("Reed")
        f = QFormLayout(self)
        self.started = QDateEdit(QDate.currentDate())
        self.started.setCalendarPopup(True)
        self.started.setDisplayFormat("M/d/yyyy")
        self._dots = reed.dots if reed else 1
        self.brand = QLineEdit(C.DEFAULT_BRAND)
        self.model = QLineEdit(C.DEFAULT_MODEL)
        self.strength = QLineEdit(C.DEFAULT_STRENGTH)
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Your thoughts on this reed")
        self.notes.setFixedHeight(90)
        if reed:
            self.started.setDate(QDate.fromString(reed.started, "yyyy-MM-dd"))
            self.brand.setText(reed.brand)
            self.model.setText(reed.model)
            self.strength.setText(reed.strength)
            self.notes.setPlainText(reed.notes)
        f.addRow("Date on reed", self.started)
        f.addRow("Brand", self.brand)
        f.addRow("Model", self.model)
        f.addRow("Strength", self.strength)
        f.addRow("Notes", self.notes)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def reed(self) -> C.Reed:
        return C.Reed(
            started=self.started.date().toString("yyyy-MM-dd"),
            dots=self._dots,
            brand=self.brand.text().strip() or C.DEFAULT_BRAND,
            model=self.model.text().strip() or C.DEFAULT_MODEL,
            strength=self.strength.text().strip() or C.DEFAULT_STRENGTH,
            notes=self.notes.toPlainText().strip(),
        )


class MainWindow(QMainWindow):
    def __init__(self, settings: C.Settings, mic_finder=choose_mic, recorder_cls=Recorder,
                 device_refresher=refresh_devices):
        super().__init__()
        self.mic_finder, self.recorder_cls, self.refresh_dev = mic_finder, recorder_cls, device_refresher
        self.mic_ok = False
        self.mic_box = None
        self.next_retry = 0.0
        self.s = settings
        b = U.current_build()
        self.setWindowTitle(C.APP_NAME + (f"  (build {b})" if b else ""))
        self.reeds = C.load_reeds(self.s.reeds_file)
        self.today = date.today()
        self.exercises = C.exercises_for(self.today)
        self.rec = None

        root = QWidget()
        v = QVBoxLayout(root)
        v.setSpacing(6)

        # microphone
        self.mic_label = QLabel()
        v.addWidget(self.mic_label)

        # reed
        hr = QHBoxLayout()
        hr.addWidget(QLabel("Reed:"))
        self.reed_box = QComboBox()
        self.reed_box.setMinimumWidth(420)
        hr.addWidget(self.reed_box, 1)
        add = QPushButton("Add reed…")
        add.clicked.connect(self.add_reed)
        edit = QPushButton("Edit reed…")
        edit.clicked.connect(self.edit_reed)
        hr.addWidget(add)
        hr.addWidget(edit)
        v.addLayout(hr)

        # dots on the reed's heel, set with three buttons
        hd = QHBoxLayout()
        hd.addWidget(QLabel("Dots on heel:"))
        self.dots_group = QButtonGroup(self)
        self.dots_group.setExclusive(True)
        for n in (1, 2, 3):
            b = QPushButton("•" * n)
            b.setCheckable(True)
            b.setMinimumWidth(80)
            b.setStyleSheet("QPushButton:checked{background:#1565c0;color:white;font-weight:bold}")
            self.dots_group.addButton(b, n)
            hd.addWidget(b)
        hd.addStretch(1)
        self.dots_group.idClicked.connect(self.set_dots)
        v.addLayout(hd)

        # exercises
        v.addWidget(QLabel("Exercise:"))
        he = QHBoxLayout()
        self.ex_group = QButtonGroup(self)
        self.ex_group.setExclusive(True)
        for i, ex in enumerate(self.exercises):
            b = QPushButton(ex.title)
            b.setCheckable(True)
            b.setMinimumHeight(56)
            b.setStyleSheet("QPushButton:checked{background:#1565c0;color:white;font-weight:bold}")
            self.ex_group.addButton(b, i)
            he.addWidget(b)
        self.test_index = len(self.exercises)
        b = QPushButton("Test")
        b.setCheckable(True)
        b.setMinimumHeight(56)
        b.setStyleSheet("QPushButton:checked{background:#6a1b9a;color:white;font-weight:bold}")
        self.ex_group.addButton(b, self.test_index)
        he.addWidget(b)
        self.ex_group.button(0).setChecked(True)
        self.ex_group.idClicked.connect(lambda _: self.refresh_labels())
        v.addLayout(he)
        ht = QHBoxLayout()
        ht.addWidget(QLabel("Test description:"))
        self.test_desc = QLineEdit()
        self.test_desc.setPlaceholderText("for example, tuner check")
        self.test_desc.textChanged.connect(lambda _: self.refresh_labels())
        ht.addWidget(self.test_desc, 1)
        self.test_row = QWidget()
        self.test_row.setLayout(ht)
        ht.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.test_row)

        # hearing aids, saved with every recording
        hh = QHBoxLayout()
        hh.addWidget(QLabel("Hearing aids:"))
        self.ha_group = QButtonGroup(self)
        self.ha_group.setExclusive(True)
        for i, txt in ((0, "Off"), (1, "On")):
            b = QPushButton(txt)
            b.setCheckable(True)
            b.setMinimumWidth(80)
            b.setStyleSheet("QPushButton:checked{background:#1565c0;color:white;font-weight:bold}")
            self.ha_group.addButton(b, i)
            hh.addWidget(b)
        hh.addStretch(1)
        self.ha_group.button(1 if self.s.hearing_aids else 0).setChecked(True)
        self.ha_group.idClicked.connect(self.set_hearing_aids)
        v.addLayout(hh)
        self.tempo_label = QLabel()
        v.addWidget(self.tempo_label)

        # level meter
        v.addWidget(QLabel("Level:"))
        self.bar = LevelBar(self.s.level_yellow_db, self.s.level_red_db)
        v.addWidget(self.bar)
        self.level_text = QLabel()
        v.addWidget(self.level_text)

        # controls
        hc = QHBoxLayout()
        self.btn_rec = QPushButton("●  Record")
        self.btn_pause = QPushButton("❚❚  Pause")
        self.btn_stop = QPushButton("■  Stop and save")
        self.btn_discard = QPushButton("✕  Discard")
        for b in (self.btn_rec, self.btn_pause, self.btn_stop, self.btn_discard):
            b.setMinimumHeight(64)
            hc.addWidget(b)
        self.btn_rec.setStyleSheet("QPushButton{background:#c62828;color:white;font-weight:bold}"
                                   "QPushButton:disabled{background:#999}")
        self.btn_rec.clicked.connect(self.start)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_discard.clicked.connect(self.discard)
        self.last_saved = None      # (path, exercise index) of the newest saved file
        v.addLayout(hc)

        self.clock = QLabel("0:00")
        self.clock.setAlignment(Qt.AlignCenter)
        cf = QFont(self.font())
        cf.setPointSize(FONT_PT * 2)
        self.clock.setFont(cf)
        v.addWidget(self.clock)

        self.loudest = QLabel("")
        self.loudest.setAlignment(Qt.AlignCenter)
        lf = QFont(self.font())
        lf.setPointSize(int(FONT_PT * 1.5))
        lf.setBold(True)
        self.loudest.setFont(lf)
        v.addWidget(self.loudest)

        self.file_label = QLabel()
        self.file_label.setWordWrap(True)
        v.addWidget(self.file_label)

        self.folder_label = QLabel()
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.folder_label)
        hf = QHBoxLayout()
        rpt = QPushButton("Reports…")
        rpt.clicked.connect(lambda: ReportsDialog(self, self.s.recordings_dir).exec())
        hf.addWidget(rpt)
        live = QPushButton("Live brightness…")
        live.clicked.connect(self.show_live)
        hf.addWidget(live)
        upd = QPushButton("Check for update")
        upd.clicked.connect(self.check_update)
        hf.addWidget(upd)
        opn = QPushButton("Open recordings folder")
        opn.clicked.connect(self.open_folder)
        hf.addWidget(opn)
        chg = QPushButton("Change folder…")
        chg.clicked.connect(self.change_folder)
        hf.addWidget(chg)
        hf.addStretch(1)
        v.addLayout(hf)

        self.status = QLabel()
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        self.report_line = QLabel()
        self.report_line.setWordWrap(True)
        hr2 = QHBoxLayout()
        hr2.addWidget(self.report_line, 1)
        self.btn_open_report = QPushButton("Open report")
        self.btn_open_report.clicked.connect(lambda: self.last_report and open_file(self.last_report))
        self.btn_open_report.setVisible(False)
        hr2.addWidget(self.btn_open_report)
        v.addLayout(hr2)
        self.last_report = None
        self._relay = _Relay()
        self._relay.done.connect(self._report_done)

        self.setCentralWidget(root)
        self.fill_reeds()
        self.reed_box.currentIndexChanged.connect(lambda _: self.refresh_labels())

        self.connect_mic(first=True)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)
        self.refresh_labels()

    # ------------------------------------------------------------ microphone
    def show_mic(self, text: str, good: bool):
        self.mic_label.setText(text)
        self.mic_label.setStyleSheet(f"color:{'#2e7d32' if good else '#c62828'};font-weight:bold")

    def connect_mic(self, first: bool = False) -> bool:
        """Find and open the mic.  Returns True when a working mic is open."""
        if not first:
            self.refresh_dev()
        try:
            mic = self.mic_finder()
        except Exception:
            mic = None
        if mic is None or not mic.found_snowball:
            # Only the Snowball will do; keep looking for it every 2 seconds.
            self.mic_ok = False
            if first:
                self.show_mic("Snowball microphone not found.  Plug it in; "
                              "the program will find it on its own.", False)
                box = QMessageBox(QMessageBox.Warning, "Microphone",
                                  "The Blue Snowball is not plugged in.\n\n"
                                  "Plug it in.  The program will find it within a few seconds, "
                                  "and this message will close on its own.", QMessageBox.Ok, self)
                box.setModal(False)
                self.mic_box = box
                QTimer.singleShot(300, lambda: self.mic_box and self.mic_box.show())
            return False
        try:
            if self.rec is None:
                self.rec = self.recorder_cls(mic)
                self.rec.open()
            else:
                self.rec.reopen(mic)
        except Exception as e:
            self.mic_ok = False
            self.show_mic(f"Microphone could not open: {e}", False)
            return False
        self.mic_ok = True
        self.show_mic(f"Microphone: {mic.name}  ✓", True)
        if self.mic_box is not None:
            self.mic_box.close()
            self.mic_box = None
        return True

    def watch_mic(self):
        """Called by the timer: detect a lost mic and try to get it back."""
        now = time.time()
        if self.mic_ok and self.rec and self.rec.mic_lost():
            self.mic_ok = False
            if self.rec.recording:
                if not self.rec.paused:
                    self.rec.pause()
                self.rec.meta.setdefault("disconnects", []).append(round(self.rec.seconds, 2))
                self.show_mic("Microphone disconnected.  Recording paused; what you played "
                              "so far is kept.  Plug the mic back in.", False)
            else:
                self.show_mic("Microphone disconnected.  Plug the mic back in.", False)
            self.next_retry = now + 2
            self.update_buttons()
        elif not self.mic_ok and now >= self.next_retry:
            self.next_retry = now + 2
            if self.connect_mic():
                if self.rec.recording:
                    self.show_mic(f"Microphone back: {self.rec.mic.name}.  "
                                  "Press Resume to continue recording.", True)
                self.update_buttons()

    # ------------------------------------------------------------ reeds
    def fill_reeds(self, select_label: str | None = None):
        self.reed_box.clear()
        active = [r for r in self.reeds if not r.retired]
        active.sort(key=lambda r: (r.started, r.dots), reverse=True)
        for r in active:
            self.reed_box.addItem(r.display, r.label)
        want = select_label or self.s.last_reed
        i = self.reed_box.findData(want)
        if i >= 0:
            self.reed_box.setCurrentIndex(i)

    def current_reed(self) -> C.Reed | None:
        lab = self.reed_box.currentData()
        return next((r for r in self.reeds if r.label == lab), None)

    def add_reed(self):
        d = ReedDialog(self)
        if d.exec() == QDialog.Accepted:
            r = d.reed()
            if any(x.label == r.label for x in self.reeds):
                QMessageBox.warning(self, "Reed", f"A reed labeled {r.label} already exists.")
                return
            self.reeds.append(r)
            C.save_reeds(self.s.reeds_file, self.reeds)
            self.fill_reeds(r.label)
            self.refresh_labels()

    def edit_reed(self):
        r = self.current_reed()
        if not r:
            return
        d = ReedDialog(self, r)
        if d.exec() == QDialog.Accepted:
            new = d.reed()
            new.adjustments, new.retired = r.adjustments, r.retired
            self.reeds[self.reeds.index(r)] = new
            C.save_reeds(self.s.reeds_file, self.reeds)
            self.fill_reeds(new.label)
            self.refresh_labels()

    def show_dots(self):
        r = self.current_reed()
        for n in (1, 2, 3):
            self.dots_group.button(n).setChecked(bool(r) and r.dots == n)

    def set_dots(self, n: int):
        """Switch to the reed with the same date and n dots.  Date plus dots
        identify one physical reed, so each keeps its own notes."""
        r = self.current_reed()
        if not r or r.dots == n:
            return
        other = next((x for x in self.reeds if x.started == r.started and x.dots == n), None)
        if other is None:
            d = date.fromisoformat(r.started)
            if QMessageBox.question(
                    self, "Reed",
                    f"No reed dated {d.month}/{d.day}/{d.year} with {n} dot(s) yet.  Add it?"
                    ) != QMessageBox.Yes:
                self.show_dots()
                return
            other = C.Reed(started=r.started, dots=n, brand=r.brand,
                           model=r.model, strength=r.strength)
            self.reeds.append(other)
            C.save_reeds(self.s.reeds_file, self.reeds)
        elif other.retired:
            other.retired = False
            C.save_reeds(self.s.reeds_file, self.reeds)
        self.fill_reeds(other.label)
        self.refresh_labels()

    # ------------------------------------------------------------ labels
    def is_test(self) -> bool:
        return self.ex_group.checkedId() == self.test_index

    def exercise(self) -> C.Exercise:
        if self.is_test():
            key = C.test_key(self.test_desc.text())
            return C.Exercise(key, "Test", C.TEST.tempo)
        return self.exercises[self.ex_group.checkedId()]

    def target_dir(self) -> Path:
        return self.s.tests_dir if self.is_test() else self.s.recordings_dir

    def show_live(self):
        if getattr(self, "live", None) is None:
            self.live = LiveBrightness(self, lambda: self.rec if self.mic_ok else None, self.s.recordings_dir)
            self.live.finished.connect(lambda _: setattr(self, "live", None))
        self.live.show()
        self.live.raise_()

    def set_hearing_aids(self, i: int):
        self.s.hearing_aids = bool(i)
        self.s.save()

    def refresh_labels(self):
        ex = self.exercise()
        test = self.is_test()
        self.test_row.setVisible(test)
        self.tempo_label.setText("Test take: saved in Recordings\\Tests; kept out of your exercise history."
                                 if test else f"Set your metronome to {ex.tempo}.")
        r = self.current_reed()
        if r is None:
            self.file_label.setText("Add a reed before recording.")
        elif not (self.rec and self.rec.recording):
            name = C.recording_name(datetime.now(), r.label, ex.key)
            self.file_label.setText(f"Next file: {name}")
        self.folder_label.setText(f"Folder: {self.target_dir()}")
        self.show_dots()
        self.update_buttons()

    def update_buttons(self):
        recording = bool(self.rec and self.rec.recording)
        ready = bool(self.rec) and self.mic_ok and self.current_reed() is not None
        self.btn_rec.setEnabled(ready and not recording)
        self.btn_pause.setEnabled(recording and (self.mic_ok or not self.rec.paused))
        self.btn_stop.setEnabled(recording)
        self.btn_discard.setEnabled(recording or self.last_saved is not None)
        self.btn_discard.setText("✕  Discard" if recording or self.last_saved is None
                                 else "✕  Discard last")
        for b in self.ex_group.buttons():
            b.setEnabled(not recording)
        for b in self.ha_group.buttons():
            b.setEnabled(not recording)
        self.test_desc.setEnabled(not recording)
        self.reed_box.setEnabled(not recording)
        for b in self.dots_group.buttons():
            b.setEnabled(not recording and self.current_reed() is not None)
        if recording:
            self.btn_pause.setText("▶  Resume" if self.rec.paused else "❚❚  Pause")

    # ------------------------------------------------------------ actions
    def start(self):
        r, ex = self.current_reed(), self.exercise()
        if not (self.rec and r):
            return
        now = datetime.now()
        folder = self.target_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "Record", f"Could not make the folder {folder}:\n{e}")
            return
        path = C.unique_path(folder, C.recording_name(now, r.label, ex.key))
        meta = {"exercise": ex.key, "exercise_title": ex.title, "tempo": ex.tempo,
                "hearing_aids": bool(self.ha_group.checkedId() == 1),
                "test_description": self.test_desc.text().strip() if self.is_test() else "",
                "reed": {"label": r.label, "started": r.started, "dots": r.dots,
                         "brand": r.brand, "model": r.model, "strength": r.strength}}
        try:
            self.rec.start(path, meta)
        except Exception as e:
            QMessageBox.critical(self, "Record", f"Could not start recording:\n{e}")
            return
        self.s.last_reed = r.label
        self.s.save()
        self.file_label.setText(f"Recording to: {path.name}")
        self.last_saved = None
        self.status.setText("")
        self.update_buttons()

    def toggle_pause(self):
        if not self.rec:
            return
        self.rec.resume() if self.rec.paused else self.rec.pause()
        self.update_buttons()

    def stop(self):
        if not (self.rec and self.rec.recording):
            return
        ex_index = self.ex_group.checkedId()
        path = self.rec.stop()
        self.last_saved = (path, ex_index)
        secs = self.rec.seconds
        _, peak, clipped = self.rec.meter.read()
        msg = (f"Saved {path.name}  ({int(secs // 60)}:{int(secs % 60):02d}).  "
               f"Loudest: {peak:.0f} dB.")
        if clipped:
            msg += "  Warning: the level hit the top (clipped).  Move the level down."
        self.status.setText(msg)
        self.status.setStyleSheet("color:#c62828" if clipped else "color:#2e7d32")
        self.clear_loudest()
        self._start_report(path)
        # advance to the next exercise (a test take stays on Test)
        if not self.is_test():
            nxt = min(self.ex_group.checkedId() + 1, len(self.exercises) - 1)
            self.ex_group.button(nxt).setChecked(True)
        self.refresh_labels()

    def discard(self, confirm: bool = True):
        recording = bool(self.rec and self.rec.recording)
        if not recording and self.last_saved is None:
            return
        if recording:
            ex_index = self.ex_group.checkedId()
            name = self.rec.path.name
        else:
            path, ex_index = self.last_saved
            name = path.name
        if confirm and QMessageBox.question(
                self, "Discard", f"Delete this recording?\n\n{name}") != QMessageBox.Yes:
            return
        path = self.rec.stop() if recording else self.last_saved[0]
        files = [path, path.with_suffix(".json"), AN.analysis_path(path), RP.report_path(path)]
        for _ in range(20):     # Windows cannot delete a file another thread has open; try for up to 2 s
            with AN.READ_LOCK:  # wait if the report is reading this file right now
                for f in list(files):
                    try:
                        f.unlink()
                        files.remove(f)
                    except FileNotFoundError:
                        files.remove(f)
                    except OSError:
                        pass
            if not files:
                break
            time.sleep(0.1)
        self.last_saved = None
        self.ex_group.button(ex_index).setChecked(True)
        self.status.setText(f"Discarded {name}.")
        self.status.setStyleSheet("color:#444")
        self.clock.setText("0:00")
        self.clear_loudest()
        self.refresh_labels()

    def _start_report(self, wav: Path):
        base = wav.parent.parent if wav.parent.name.lower() == "tests" else wav.parent
        old = len(stale_recordings(base, skip=wav))
        extra = (f"  First, {old} earlier recording(s) are measured again with the new measures; "
                 "this may take a minute or two.") if old else ""
        self.report_line.setText(f"Measuring {wav.name}…{extra}")
        self.report_line.setStyleSheet("color:#444")
        self.btn_open_report.setVisible(False)

        def work():
            try:
                make_report(wav)
                self._relay.done.emit(str(wav), "")
            except Exception as e:
                self._relay.done.emit(str(wav), str(e) or e.__class__.__name__)
        threading.Thread(target=work, daemon=True).start()

    def _report_done(self, wav: str, err: str):
        wav = Path(wav)
        if not wav.exists():          # discarded while it was being measured
            for f in (AN.analysis_path(wav), RP.report_path(wav)):
                try:
                    f.unlink()
                except OSError:
                    pass
            self.report_line.setText("")
            return
        if err:
            self.report_line.setText(f"Could not measure {wav.name}: {err}")
            self.report_line.setStyleSheet("color:#c62828")
            return
        try:
            import json
            s = json.loads(AN.analysis_path(wav).read_text(encoding="utf-8"))["summary"]
            line = (f"{wav.stem}:  pitch error {s['cents_abs']:.1f} cents,  wobble {s['wobble_cents']:.1f} cents,  "
                    f"unsteadiness {s['steadiness_pct']:.1f}%,  buzz {s['buzz']:.3f},  "
                    f"harmonic-to-noise {s['hnr_db']:.0f} dB.")
        except Exception:
            line = f"Report ready for {wav.name}."
        self.report_line.setText(line)
        self.report_line.setStyleSheet("color:#1f2328")
        self.last_report = RP.report_path(wav)
        self.btn_open_report.setVisible(True)

    def clear_loudest(self):
        if self.rec:
            self.rec.meter.reset()
        self.loudest.setText("")
        self.bar.set_levels(LevelBar.LO, LevelBar.LO)

    def open_folder(self):
        d = self.s.recordings_dir
        try:
            d.mkdir(parents=True, exist_ok=True)
            C.set_general_view(d)
            if os.name == "nt":
                os.startfile(str(d))
            else:
                subprocess.Popen(["xdg-open", str(d)])
        except Exception as e:
            QMessageBox.warning(self, "Folder", f"Could not open {d}:\n{e}")

    def start_update_check(self):
        """At startup, look for a newer build in the background; ask only if one exists."""
        if not U.current_build():
            return          # running from source, not a GitHub build

        class Relay(QObject):
            found = Signal(int)
        self._upd_relay = Relay()     # must not replace self._relay, which carries "report done"
        self._upd_relay.found.connect(self._offer_update)

        def work():
            try:
                latest, _ = U.latest_release()
            except Exception:
                return      # no internet: say nothing
            if latest > U.current_build():
                self._upd_relay.found.emit(latest)
        threading.Thread(target=work, daemon=True).start()

    def _offer_update(self, latest: int):
        if self.rec and self.rec.recording:
            return
        self.check_update()

    def check_update(self):
        if self.rec and self.rec.recording:
            QMessageBox.information(self, "Update", "Stop the recording first.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            latest, url = U.latest_release()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Update", f"Could not reach GitHub:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        mine = U.current_build()
        if latest <= mine:
            QMessageBox.information(self, "Update", f"You have the newest version (build {mine}).")
            return
        folder = Path(self.s.base_dir)
        if QMessageBox.question(
                self, "Update",
                f"Build {latest} is available (you have build {mine or 'unknown'}).\n\n"
                f"Download it to\n{folder}\nand restart the program?") != QMessageBox.Yes:
            return
        prog = QProgressDialog("Downloading…", "Cancel", 0, 100, self)
        prog.setWindowTitle("Update")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)

        def step(done, total):
            if total:
                prog.setValue(int(done * 100 / total))
            QApplication.processEvents()
            return not prog.wasCanceled()

        new = folder / "ClarinetTone.new.exe"
        try:
            U.download(url, new, step)
            prog.close()
            exe = U.install(new, folder)
        except Exception as e:
            prog.close()
            try:
                new.unlink()
            except OSError:
                pass
            if not isinstance(e, InterruptedError):
                QMessageBox.warning(self, "Update", f"The update failed:\n{e}")
            return
        running = U.running_exe()
        note = ""
        if running and running.parent != folder.resolve():
            note = (f"\n\nFrom now on, use the copy in\n{folder}\n"
                    f"You may delete this one:\n{running}")
        QMessageBox.information(self, "Update", f"Build {latest} is installed.  "
                                "The program will now restart." + note)
        if self.rec:
            self.rec.close()
            self.rec = None
        U.launch(exe)
        QApplication.quit()     # make sure this copy really exits

    def change_folder(self):
        if self.rec and self.rec.recording:
            return
        d = QFileDialog.getExistingDirectory(self, "Choose the Clarinet tone folder", self.s.base_dir)
        if d:
            self.s.base_dir = d
            self.s.save()
            self.reeds = C.load_reeds(self.s.reeds_file)
            self.fill_reeds()
            self.refresh_labels()

    # ------------------------------------------------------------ meter
    def tick(self):
        self.watch_mic()
        if not (self.rec and self.mic_ok):
            if self.rec and self.rec.recording:
                s = self.rec.seconds
                self.clock.setText(f"{int(s // 60)}:{int(s % 60):02d}  (paused)")
            return
        level, hold, clipped = self.rec.meter.read()
        self.bar.set_levels(level, hold)
        if clipped:
            txt, col = "CLIPPED: level hit the top.  Move the level down.", "#c62828"
        elif hold > self.s.level_red_db:
            txt, col = f"Loudest so far: {hold:.0f} dB.  Too loud: move the level down.", "#c62828"
        elif hold > self.s.level_yellow_db:
            txt, col = f"Loudest so far: {hold:.0f} dB.  Near the top: watch it.", "#b8860b"
        elif hold > -18:
            txt, col = f"Loudest so far: {hold:.0f} dB.  Good.", "#2e7d32"
        elif hold > -100:
            txt, col = f"Loudest so far: {hold:.0f} dB.  Quiet: move the level up if your loudest notes stay here.", "#444"
        else:
            txt, col = "No sound yet.", "#444"
        self.level_text.setText(txt)
        self.level_text.setStyleSheet(f"color:{col}")
        if self.rec.recording:
            s = self.rec.seconds
            self.clock.setText(f"{int(s // 60)}:{int(s % 60):02d}" + ("  (paused)" if self.rec.paused else ""))
            if hold > -100:
                self.loudest.setText(f"Loudest this take: {hold:.0f} dB" + ("  CLIPPED" if clipped else ""))
                self.loudest.setStyleSheet(f"color:{col}")

    def closeEvent(self, e):
        if self.rec and self.rec.recording:
            if QMessageBox.question(self, "Quit", "Recording in progress.  Stop and save it?") != QMessageBox.Yes:
                e.ignore()
                return
            self.stop()
        if self.rec:
            self.rec.close()
        e.accept()


def icon_path() -> Path:
    import sys
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / "clarinet.ico"


def make_desktop_shortcut(exe: Path) -> None:
    """Put a Clarinet Tone shortcut on the desktop (runs PowerShell hidden)."""
    ps = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Clarinet Tone.lnk'));"
        f"$s.TargetPath='{exe}';$s.WorkingDirectory='{exe.parent}';"
        f"$s.IconLocation='{exe},0';$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   creationflags=0x08000000, timeout=30, check=True)


def run():
    import sys
    if os.name == "nt":
        try:    # show this program's own icon on the taskbar
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Silverstein.ClarinetTone")
        except Exception:
            pass
    app = QApplication(sys.argv)
    if icon_path().exists():
        app.setWindowIcon(QIcon(str(icon_path())))
    f = QFont("Segoe UI", FONT_PT)
    app.setFont(f)
    s = C.Settings.load()
    if not s.base_dir:
        QMessageBox.information(None, C.APP_NAME,
            "Please choose your Clarinet tone folder\n"
            "(Documents\\Claude\\Clarinet tone).")
        d = QFileDialog.getExistingDirectory(None, "Choose the Clarinet tone folder")
        if not d:
            return 0
        s.base_dir = d
    s.save()
    try:
        s.recordings_dir.mkdir(parents=True, exist_ok=True)
        C.set_general_view(s.recordings_dir)
    except OSError as e:
        QMessageBox.critical(None, C.APP_NAME, f"Cannot use the folder {s.recordings_dir}:\n{e}")
        return 1
    U.clean_old(Path(s.base_dir))
    exe = U.running_exe()
    if exe and not s.shortcut_made and exe.parent == Path(s.base_dir).resolve():
        def mk():
            try:
                make_desktop_shortcut(exe)
                s.shortcut_made = True
                s.save()
            except Exception:
                pass
        threading.Thread(target=mk, daemon=True).start()
    w = MainWindow(s)
    hint = w.sizeHint()
    w.resize(max(900, hint.width()), hint.height())
    w.show()
    w.start_update_check()
    return app.exec()
