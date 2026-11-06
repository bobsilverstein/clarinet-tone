"""Runs the window off-screen with a simulated microphone."""
import json, os, sys, threading, time
from datetime import date, datetime
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np, soundfile as sf
from clarinet_tone import config as C
from clarinet_tone.recorder import Recorder, MicChoice

class FakeRecorder(Recorder):
    def open(self):
        self._run = True
        def gen():
            t = 0
            while self._run:
                n = 1024
                x = 0.5*np.sin(2*np.pi*233.08*(np.arange(t, t+n)/C.SAMPLE_RATE)).astype(np.float32)
                self._callback(x[:, None], n, None, None); t += n
                time.sleep(n/C.SAMPLE_RATE)
        threading.Thread(target=gen, daemon=True).start()
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
