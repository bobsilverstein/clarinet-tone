"""Main window."""
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QDate
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from . import config as C
from .recorder import Recorder, choose_mic

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
        self.dots = QSpinBox()
        self.dots.setRange(1, 3)
        self.brand = QLineEdit(C.DEFAULT_BRAND)
        self.model = QLineEdit(C.DEFAULT_MODEL)
        self.strength = QLineEdit(C.DEFAULT_STRENGTH)
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Your thoughts on this reed")
        self.notes.setFixedHeight(90)
        if reed:
            self.started.setDate(QDate.fromString(reed.started, "yyyy-MM-dd"))
            self.dots.setValue(reed.dots)
            self.brand.setText(reed.brand)
            self.model.setText(reed.model)
            self.strength.setText(reed.strength)
            self.notes.setPlainText(reed.notes)
        f.addRow("Date on reed", self.started)
        f.addRow("Dots on heel", self.dots)
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
            dots=self.dots.value(),
            brand=self.brand.text().strip() or C.DEFAULT_BRAND,
            model=self.model.text().strip() or C.DEFAULT_MODEL,
            strength=self.strength.text().strip() or C.DEFAULT_STRENGTH,
            notes=self.notes.toPlainText().strip(),
        )


class MainWindow(QMainWindow):
    def __init__(self, settings: C.Settings, mic_finder=choose_mic, recorder_cls=Recorder):
        super().__init__()
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

        self.file_label = QLabel()
        self.file_label.setWordWrap(True)
        v.addWidget(self.file_label)

        hf = QHBoxLayout()
        self.folder_label = QLabel()
        self.folder_label.setWordWrap(True)
        hf.addWidget(self.folder_label, 1)
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

        # microphone
        mic = mic_finder()
        if mic is None:
            self.mic_label.setText("Microphone: none found.  Plug in the Snowball and restart.")
            self.mic_label.setStyleSheet("color:#c62828;font-weight:bold")
        else:
            self.rec = recorder_cls(mic)
            try:
                self.rec.open()
                if mic.found_snowball:
                    self.mic_label.setText(f"Microphone: {mic.name}  ✓")
                    self.mic_label.setStyleSheet("color:#2e7d32;font-weight:bold")
                else:
                    self.mic_label.setText(f"Snowball not found.  Using: {mic.name}")
                    self.mic_label.setStyleSheet("color:#c62828;font-weight:bold")
            except Exception as e:
                self.rec = None
                self.mic_label.setText(f"Microphone could not open: {e}")
                self.mic_label.setStyleSheet("color:#c62828;font-weight:bold")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)
        self.refresh_labels()

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
        self.update_buttons()

    def update_buttons(self):
        recording = bool(self.rec and self.rec.recording)
        ready = bool(self.rec) and self.current_reed() is not None
        self.btn_rec.setEnabled(ready and not recording)
        self.btn_pause.setEnabled(recording)
        self.btn_stop.setEnabled(recording)
        self.btn_discard.setEnabled(recording or self.last_saved is not None)
        self.btn_discard.setText("✕  Discard" if recording or self.last_saved is None
                                 else "✕  Discard last")
        for b in self.ex_group.buttons():
            b.setEnabled(not recording)
        self.reed_box.setEnabled(not recording)
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
        msg = f"Saved {path.name}  ({int(secs // 60)}:{int(secs % 60):02d})."
        if clipped:
            msg += "  Warning: the level hit the top (clipped).  Move the level down."
        self.status.setText(msg)
        self.status.setStyleSheet("color:#c62828" if clipped else "color:#2e7d32")
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
        self.refresh_labels()

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
        if not self.rec:
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
    except OSError as e:
        QMessageBox.critical(None, C.APP_NAME, f"Cannot use the folder {s.recordings_dir}:\n{e}")
        return 1
    w = MainWindow(s)
    w.resize(900, 720)
    w.show()
    return app.exec()
