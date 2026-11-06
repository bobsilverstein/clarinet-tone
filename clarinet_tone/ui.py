"""Main window."""
import os
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QDate
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from . import config as C
from .recorder import Recorder, choose_mic, refresh_devices

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
        self.setWindowTitle(C.APP_NAME)
        self.reeds = C.load_reeds(self.s.reeds_file)
        self.today = date.today()
        self.exercises = C.exercises_for(self.today)
        self.rec = None

        root = QWidget()
        v = QVBoxLayout(root)
        v.setSpacing(12)

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
        self.ex_group.button(0).setChecked(True)
        self.ex_group.idClicked.connect(lambda _: self.refresh_labels())
        v.addLayout(he)
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

        hf = QHBoxLayout()
        self.folder_label = QLabel()
        self.folder_label.setWordWrap(True)
        hf.addWidget(self.folder_label, 1)
        opn = QPushButton("Open recordings folder")
        opn.clicked.connect(self.open_folder)
        hf.addWidget(opn)
        chg = QPushButton("Change folder…")
        chg.clicked.connect(self.change_folder)
        hf.addWidget(chg)
        v.addLayout(hf)

        self.status = QLabel()
        self.status.setWordWrap(True)
        v.addWidget(self.status)

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
        r = self.current_reed()
        if not r or r.dots == n:
            return
        new_label = C.Reed(started=r.started, dots=n).label
        if any(x is not r and x.label == new_label for x in self.reeds):
            QMessageBox.warning(self, "Reed", f"A reed labeled {new_label} already exists.")
            self.show_dots()
            return
        r.adjustments.append({"date": date.today().isoformat(), "what": f"dots {r.dots} to {n}"})
        r.dots = n      # only the dots change; the date stays as written on the reed
        C.save_reeds(self.s.reeds_file, self.reeds)
        self.fill_reeds(r.label)
        self.refresh_labels()

    # ------------------------------------------------------------ labels
    def exercise(self) -> C.Exercise:
        return self.exercises[self.ex_group.checkedId()]

    def refresh_labels(self):
        ex = self.exercise()
        self.tempo_label.setText(f"Set your metronome to {ex.tempo}.")
        r = self.current_reed()
        if r is None:
            self.file_label.setText("Add a reed before recording.")
        elif not (self.rec and self.rec.recording):
            name = C.recording_name(datetime.now(), r.label, ex.key)
            self.file_label.setText(f"Next file: {name}")
        self.folder_label.setText(f"Folder: {self.s.recordings_dir}")
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
        path = C.unique_path(self.s.recordings_dir, C.recording_name(now, r.label, ex.key))
        meta = {"exercise": ex.key, "exercise_title": ex.title, "tempo": ex.tempo,
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
        # advance to the next exercise
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
        for f in (path, path.with_suffix(".json")):
            try:
                f.unlink()
            except OSError:
                pass
        self.last_saved = None
        self.ex_group.button(ex_index).setChecked(True)
        self.status.setText(f"Discarded {name}.")
        self.status.setStyleSheet("color:#444")
        self.clock.setText("0:00")
        self.clear_loudest()
        self.refresh_labels()

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


def run():
    import sys
    app = QApplication(sys.argv)
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
    w = MainWindow(s)
    w.resize(900, 720)
    w.show()
    return app.exec()
