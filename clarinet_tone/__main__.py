import sys
from clarinet_tone.ui import run

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import clarinet_tone.recorder, clarinet_tone.config  # noqa: F401
        print("ok")
        sys.exit(0)
    sys.exit(run())
