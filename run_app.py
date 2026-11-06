import os
import sys
import traceback
from pathlib import Path


def _log_dir() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home()))
    d = root / "ClarinetTone"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _show_error(text: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Clarinet Tone Tracker", 0x10)
    except Exception:
        print(text, file=sys.stderr)


def main() -> int:
    if "--selftest" in sys.argv:
        # Used by the GitHub build to prove the packaged program starts.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import numpy, soundfile, sounddevice  # noqa: F401
        from PySide6.QtWidgets import QApplication
        from clarinet_tone import ui  # noqa: F401
        app = QApplication([])
        sounddevice.query_devices()
        (_log_dir() / "selftest.txt").write_text("ok", encoding="utf-8")
        return 0
    from clarinet_tone.ui import run
    return run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        tb = traceback.format_exc()
        log = _log_dir() / "error.log"
        try:
            log.write_text(tb, encoding="utf-8")
        except Exception:
            pass
        _show_error("The program stopped with an error.\n\n"
                    f"Details were saved to:\n{log}\n\n{tb[-800:]}")
        sys.exit(1)
