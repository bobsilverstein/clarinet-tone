"""Runs the window off-screen with a simulated microphone."""
import json, os, sys, threading, time
from datetime import date, datetime
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np, soundfile as sf
from clarinet_tone import config as C
from clarinet_tone.recorder import Recorder, MicChoice

import types
PLUGGED = {"on": True}

class FakeRecorder(Recorder):
    def open(self):
        self._run = True
        self.stream_error = ""; self.silent_since = None
        self._stream = types.SimpleNamespace(active=True, abort=lambda: None, close=lambda: None)
        self.last_callback = time.time()
        def gen():
            t = 0
            while self._run and PLUGGED["on"]:
                n = 1024
                x = 0.5*np.sin(2*np.pi*233.08*(np.arange(t, t+n)/C.SAMPLE_RATE)).astype(np.float32)
                self._callback(x[:, None], n, None, None); t += n
                time.sleep(n/C.SAMPLE_RATE)
        threading.Thread(target=gen, daemon=True).start()
    def _close_stream(self):
        self._run = False; self._stream = None
    def close(self):
        super().close(); self._run = False

def test_names():
    assert C.recording_name(datetime(2026,11,5,18,45), "0804-1", "register") == "2026-11-05_1845_reed-0804-1_register.wav"
    assert C.long_tone_for(date(2026,11,5)).key == "long-tone-chalumeau"
    assert C.long_tone_for(date(2026,11,6)).key == "long-tone-clarion"
    r = C.Reed(started="2026-08-04", dots=1)
    assert r.label == "0804-1" and r.brand == "Vandoren" and r.strength == "3"

def test_window(tmp_path):
    os.environ["APPDATA"] = str(tmp_path / "appdata")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from clarinet_tone.ui import MainWindow
    s = C.Settings(base_dir=str(tmp_path / "Clarinet tone"))
    C.save_reeds(s.reeds_file, [C.Reed(started="2026-08-04", dots=1)])
    w = MainWindow(s, mic_finder=lambda: MicChoice(0, "Microphone (Blue Snowball)", "MME", True),
                   recorder_cls=FakeRecorder)
    assert "Snowball" in w.mic_label.text()
    assert w.btn_rec.isEnabled()
    w.start()
    t0 = time.time()
    while time.time() - t0 < 1.0: app.processEvents(); time.sleep(0.02)
    w.toggle_pause(); time.sleep(0.4); w.toggle_pause()
    t0 = time.time()
    while time.time() - t0 < 0.6: app.processEvents(); time.sleep(0.02)
    w.stop()
    files = list(s.recordings_dir.glob("*.wav"))
    assert len(files) == 1, files
    info = sf.info(str(files[0]))
    assert info.samplerate == 48000 and info.subtype == "PCM_24" and info.channels == 1
    assert 1.3 < info.duration < 1.9, info.duration
    meta = json.loads(files[0].with_suffix(".json").read_text())
    assert meta["microphone"] == "Microphone (Blue Snowball)" and meta["reed"]["brand"] == "Vandoren"
    assert len(meta["pauses"]) == 1 and meta["tempo"] == "88 bpm, 4/4"
    assert -7 < meta["peak_dbfs"] < -5
    assert w.ex_group.checkedId() == 1   # advanced to legato
    print(files[0].name, info.duration, meta["peak_dbfs"], w.level_text.text(), w.status.text())
    w.grab().save(str(tmp_path / "window.png"))
    w.close()

def test_find_base_dir(tmp_path, monkeypatch):
    docs = tmp_path / "G" / "Users" / "Bob" / "Documents"
    (docs / "Claude" / "Clarinet tone").mkdir(parents=True)
    monkeypatch.setattr(C, "candidate_documents", lambda: [tmp_path / "OneDrive" / "OneNote", docs])
    assert C.find_base_dir() == docs / "Claude" / "Clarinet tone"
    monkeypatch.setattr(C, "candidate_documents", lambda: [tmp_path / "nowhere"])
    assert C.find_base_dir() is None

def test_discard(tmp_path):
    os.environ["APPDATA"] = str(tmp_path / "appdata")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from clarinet_tone.ui import MainWindow
    s = C.Settings(base_dir=str(tmp_path / "Clarinet tone"))
    C.save_reeds(s.reeds_file, [C.Reed(started="2026-08-04", dots=1)])
    w = MainWindow(s, mic_finder=lambda: MicChoice(0, "Blue Snowball", "MME", True), recorder_cls=FakeRecorder)
    assert not w.btn_discard.isEnabled()
    # discard while recording
    w.start(); time.sleep(0.3); w.discard(confirm=False)
    assert list(s.recordings_dir.glob("*")) == [] and w.ex_group.checkedId() == 0
    # discard after saving
    w.start(); time.sleep(0.3); w.stop()
    assert len(list(s.recordings_dir.glob("*"))) == 2 and w.ex_group.checkedId() == 1
    assert w.btn_discard.isEnabled() and "last" in w.btn_discard.text()
    w.discard(confirm=False)
    assert list(s.recordings_dir.glob("*")) == [] and w.ex_group.checkedId() == 0
    assert not w.btn_discard.isEnabled()
    w.close()


def finder():
    return MicChoice(0, "Blue Snowball", "MME", True) if PLUGGED["on"] else None

def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents(); time.sleep(0.02)

def wait_for(app, cond, secs=6.0):
    t0 = time.time()
    while time.time() - t0 < secs and not cond():
        app.processEvents(); time.sleep(0.02)
    return cond()

def test_unplug(tmp_path):
    os.environ["APPDATA"] = str(tmp_path / "appdata")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from clarinet_tone.ui import MainWindow
    s = C.Settings(base_dir=str(tmp_path / "Clarinet tone"))
    C.save_reeds(s.reeds_file, [C.Reed(started="2026-08-04", dots=1)])
    PLUGGED["on"] = True
    w = MainWindow(s, mic_finder=finder, recorder_cls=FakeRecorder, device_refresher=lambda: None)
    w.start(); pump(app, 0.8)
    PLUGGED["on"] = False
    wait_for(app, lambda: not w.mic_ok)
    assert not w.mic_ok and w.rec.paused and "disconnected" in w.mic_label.text()
    assert not w.btn_pause.isEnabled() and w.btn_stop.isEnabled()
    secs_at_loss = w.rec.seconds
    PLUGGED["on"] = True
    wait_for(app, lambda: w.mic_ok)
    assert w.mic_ok and "back" in w.mic_label.text() and w.rec.paused
    w.toggle_pause(); pump(app, 0.6); w.stop()
    f = next(s.recordings_dir.glob("*.wav"))
    meta = json.loads(f.with_suffix(".json").read_text())
    assert meta["disconnects"] and meta["microphone_changes"]
    assert sf.info(str(f)).duration > secs_at_loss + 0.3
    # unplugged while idle: Record disabled until it returns
    PLUGGED["on"] = False; wait_for(app, lambda: not w.btn_rec.isEnabled())
    assert not w.btn_rec.isEnabled()
    PLUGGED["on"] = True; wait_for(app, lambda: w.btn_rec.isEnabled())
    assert w.btn_rec.isEnabled() and "✓" in w.mic_label.text()
    w.close()


def test_start_without_snowball(tmp_path):
    os.environ["APPDATA"] = str(tmp_path / "appdata")
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    from clarinet_tone.ui import MainWindow
    s = C.Settings(base_dir=str(tmp_path / "Clarinet tone"))
    C.save_reeds(s.reeds_file, [C.Reed(started="2026-08-04", dots=1)])
    PLUGGED["on"] = False
    w = MainWindow(s, mic_finder=finder, recorder_cls=FakeRecorder, device_refresher=lambda: None)
    pump(app, 0.5)
    assert not w.btn_rec.isEnabled() and "not found" in w.mic_label.text()
    # a webcam mic alone is not accepted
    w.mic_finder = lambda: MicChoice(1, "Logitech webcam", "MME", False)
    pump(app, 2.3)
    assert not w.btn_rec.isEnabled()
    w.mic_finder = finder
    PLUGGED["on"] = True; pump(app, 2.3)
    assert w.btn_rec.isEnabled() and "✓" in w.mic_label.text()
    w.close()


def test_dots_buttons_and_loudest(tmp_path):
    os.environ["APPDATA"] = str(tmp_path / "appdata")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from clarinet_tone.ui import MainWindow
    s = C.Settings(base_dir=str(tmp_path / "Clarinet tone"))
    C.save_reeds(s.reeds_file, [C.Reed(started="2026-08-04", dots=1)])
    w = MainWindow(s, mic_finder=lambda: MicChoice(0, "Blue Snowball", "MME", True), recorder_cls=FakeRecorder)
    assert w.reed_box.currentText().endswith("•") and w.dots_group.checkedId() == 1
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    w.current_reed().notes = "one-dot notes"
    w.dots_group.button(3).click()
    reeds = {r.label: r for r in C.load_reeds(s.reeds_file)}
    assert set(reeds) == {"0804-1", "0804-3"}
    assert reeds["0804-1"].notes == "one-dot notes" and reeds["0804-3"].notes == ""
    assert w.reed_box.currentText().endswith("•••") and w.dots_group.checkedId() == 3
    w.dots_group.button(1).click()
    assert w.current_reed().label == "0804-1" and w.reed_box.count() == 2
    w.dots_group.button(3).click()
    w.start(); pump(app, 0.6)
    assert "Loudest this take" in w.loudest.text()
    assert not w.dots_group.button(1).isEnabled()
    w.stop()
    assert w.loudest.text() == "" and "Loudest:" in w.status.text()
    w.close()


def test_mic_message_closes_when_plugged_in(tmp_path):
    os.environ["APPDATA"] = str(tmp_path / "appdata")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from clarinet_tone.ui import MainWindow
    s = C.Settings(base_dir=str(tmp_path / "Clarinet tone"))
    C.save_reeds(s.reeds_file, [C.Reed(started="2026-08-04", dots=1)])
    PLUGGED["on"] = False
    w = MainWindow(s, mic_finder=finder, recorder_cls=FakeRecorder, device_refresher=lambda: None)
    pump(app, 0.5)
    box = w.mic_box
    assert box is not None and box.isVisible()
    PLUGGED["on"] = True; pump(app, 2.3)
    assert w.mic_box is None and not box.isVisible() and w.btn_rec.isEnabled()
    w.close()


def test_undo_old_dot_change(tmp_path):
    f = tmp_path / "reeds.json"
    C.save_reeds(f, [C.Reed(started="2026-08-04", dots=3, notes="Nice and open",
                            adjustments=[{"date": "2026-11-06", "what": "dots 1 to 3"}])])
    r = C.load_reeds(f)[0]
    assert r.dots == 1 and r.notes == "Nice and open" and r.adjustments == []
    assert C.load_reeds(f)[0].dots == 1     # saved back to disk


def test_updater_install(tmp_path):
    from clarinet_tone import updater as U
    (tmp_path / "ClarinetTone.exe").write_text("old")
    new = tmp_path / "ClarinetTone.new.exe"; new.write_text("new")
    (tmp_path / "ClarinetTone.old.exe").write_text("stale")
    exe = U.install(new, tmp_path)
    olds = list(tmp_path.glob("ClarinetTone.old*.exe"))
    assert exe.read_text() == "new" and [o.read_text() for o in olds] == ["old"]
    U.clean_old(tmp_path)
    assert not list(tmp_path.glob("ClarinetTone.old*.exe")) and not new.exists()
    assert U.current_build() >= 0


def test_startup_update_check(tmp_path, monkeypatch):
    os.environ["APPDATA"] = str(tmp_path / "appdata")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from clarinet_tone import updater as U
    from clarinet_tone.ui import MainWindow
    monkeypatch.setattr(U, "current_build", lambda: 5)
    monkeypatch.setattr(U, "latest_release", lambda: (6, "http://x"))
    s = C.Settings(base_dir=str(tmp_path / "Clarinet tone"))
    w = MainWindow(s, mic_finder=lambda: MicChoice(0, "Blue Snowball", "MME", True), recorder_cls=FakeRecorder)
    offered = []
    w.check_update = lambda: offered.append(1)
    w.start_update_check()
    wait_for(app, lambda: offered, 3)
    assert offered
    w.close()


def test_report_after_save(tmp_path):
    os.environ["APPDATA"] = str(tmp_path / "appdata")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from clarinet_tone.ui import MainWindow, ReportsDialog
    from clarinet_tone import analysis as AN, report as RP
    s = C.Settings(base_dir=str(tmp_path / "Clarinet tone"))
    C.save_reeds(s.reeds_file, [C.Reed(started="2026-08-04", dots=1)])
    w = MainWindow(s, mic_finder=lambda: MicChoice(0, "Blue Snowball", "MME", True), recorder_cls=FakeRecorder)
    PLUGGED["on"] = True
    w.start(); pump(app, 2.2); w.stop()
    wav = w.last_saved[0]
    assert wait_for(app, lambda: not w.btn_open_report.isHidden(), 20), w.report_line.text()
    assert RP.report_path(wav).exists() and AN.analysis_path(wav).exists()
    res = json.loads(AN.analysis_path(wav).read_text())
    assert res["notes"] and res["notes"][0]["written"] == "C4" and abs(res["notes"][0]["cents"]) < 2
    assert "pitch error" in w.report_line.text()
    assert res["notes"][0]["buzz"] < 0.2            # a pure steady tone has no buzz
    d = ReportsDialog(w, s.recordings_dir)
    assert d.lst.count() == 1 and not d.btn_make.isEnabled()
    w.discard(confirm=False)
    assert not RP.report_path(wav).exists()
    w.close()


def test_missing_reports(tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from clarinet_tone.ui import ReportsDialog
    folder = tmp_path / "Recordings"; folder.mkdir()
    t = np.arange(int(C.SAMPLE_RATE * 3)) / C.SAMPLE_RATE
    for name, f in (("2026-11-05_1731_reed-0804_1_long-tone.wav", 196.0), ("2026-11-06_0900_reed-0804-1_long-tone-clarion.wav", 392.0)):
        sf.write(folder / name, (0.4 * np.sin(2 * np.pi * f * t)).astype(np.float32), C.SAMPLE_RATE, subtype="PCM_24")
    d = ReportsDialog(None, folder)
    assert d.btn_make.isEnabled()
    d.make_missing()
    assert d.lst.count() == 2 and not d.btn_make.isEnabled()
    html_text = (folder / "2026-11-05_1731_reed-0804_1_long-tone.report.html").read_text(encoding="utf-8")
    assert "Long tones" in html_text and ">A3<" in html_text    # 196 Hz sounds G3, written A3


def test_build18_features(tmp_path, monkeypatch):
    """Hearing aids, test mode, cents units, and the report reaching the window
    even after the startup update check has run."""
    os.environ["APPDATA"] = str(tmp_path / "appdata")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from clarinet_tone import updater as U, analysis as AN, report as RP
    from clarinet_tone.ui import MainWindow, ReportsDialog
    monkeypatch.setattr(U, "current_build", lambda: 5)
    monkeypatch.setattr(U, "latest_release", lambda: (5, "http://x"))
    s = C.Settings(base_dir=str(tmp_path / "Clarinet tone"))
    C.save_reeds(s.reeds_file, [C.Reed(started="2026-08-04", dots=2)])
    w = MainWindow(s, mic_finder=lambda: MicChoice(0, "Blue Snowball", "MME", True), recorder_cls=FakeRecorder)
    w.start_update_check()
    pump(app, 0.5)
    PLUGGED["on"] = True
    # hearing aids on, normal exercise
    w.ha_group.button(1).click()
    assert C.Settings.load().hearing_aids is True
    w.start(); pump(app, 2.2); w.stop()
    wav = w.last_saved[0]
    assert wait_for(app, lambda: not w.btn_open_report.isHidden(), 20), w.report_line.text()
    assert "Measuring" not in w.report_line.text() and "wobble" in w.report_line.text()
    res = json.loads(AN.analysis_path(wav).read_text())
    assert res["version"] == AN.VERSION and res["hearing_aids"] is True
    n = res["notes"][0]
    assert "wobble_cents" in n and "sag_cents" in n and n["wobble_cents"] < 1
    page = RP.report_path(wav).read_text(encoding="utf-8")
    assert "Hearing aids on" in page and "center of gravity" not in page.lower()
    assert ">Unit<" not in page and " cents</td>" in page and "Wobble, cents" in page
    # test take
    w.ex_group.button(w.test_index).click()
    assert not w.test_row.isHidden()
    w.test_desc.setText("Tuner check!")
    w.ha_group.button(0).click()
    w.start(); pump(app, 2.2); w.stop()
    tw = w.last_saved[0]
    assert tw.parent == s.tests_dir and tw.name.endswith("_test-tuner-check.wav"), tw
    assert w.is_test()                       # stays on Test
    assert wait_for(app, lambda: RP.report_path(tw).exists() and not w.btn_open_report.isHidden()
                    and w.last_report == RP.report_path(tw), 20)
    tres = json.loads(AN.analysis_path(tw).read_text())
    assert AN.is_test(tres["exercise"]) and tres["hearing_aids"] is False
    tpage = RP.report_path(tw).read_text(encoding="utf-8")
    assert "Test: Tuner check!" in tpage and "This reed, last 5" not in tpage
    assert all(not AN.is_test(r["exercise"]) for r in AN.history(s.recordings_dir))
    d = ReportsDialog(w, s.recordings_dir)
    assert d.lst.count() == 2 and not d.btn_make.isEnabled()
    w.close()


def test_old_sessions_remeasured(tmp_path):
    """Analyses from version 1 (wobble in %) are measured again before a new report."""
    from clarinet_tone import analysis as AN
    from clarinet_tone.ui import make_report, stale_recordings
    folder = tmp_path / "Recordings"; folder.mkdir()
    t = np.arange(int(C.SAMPLE_RATE * 3)) / C.SAMPLE_RATE
    old = folder / "2026-11-05_1731_reed-0804-1_legato.wav"
    new = folder / "2026-11-06_1702_reed-0804-1_legato.wav"
    for p in (old, new):
        sf.write(p, (0.4 * np.sin(2 * np.pi * 261.6 * t)).astype(np.float32), C.SAMPLE_RATE, subtype="PCM_24")
    AN.analysis_path(old).write_text(json.dumps({"version": 1, "summary": {"wobble_pct": 0.1}}))
    assert stale_recordings(folder) == [old, new]
    make_report(new)
    r = json.loads(AN.analysis_path(old).read_text())
    assert r["version"] == AN.VERSION and "wobble_cents" in r["summary"] and r["hearing_aids"] is False
    assert stale_recordings(folder) == []
    assert C.test_key("  tuner check ") == "test-tuner-check" and C.test_key("!!") == "test"
