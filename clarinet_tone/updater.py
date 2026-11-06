"""Check GitHub for a newer build and install it in the Clarinet tone folder."""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

LATEST_URL = "https://api.github.com/repos/bobsilverstein/clarinet-tone/releases/latest"
EXE_NAME = "ClarinetTone.exe"


def current_build() -> int:
    try:
        from ._build import BUILD
        return int(BUILD)
    except Exception:
        return 0


def running_exe() -> Path | None:
    """The .exe this program runs from, or None when run from source."""
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


def latest_release(timeout: float = 15) -> tuple[int, str]:
    """(build number, download URL) of the newest release."""
    req = urllib.request.Request(LATEST_URL, headers={"User-Agent": "ClarinetTone-updater",
                                                      "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    build = int(str(data["tag_name"]).split("-")[-1])
    url = next(a["browser_download_url"] for a in data["assets"] if a["name"] == EXE_NAME)
    return build, url


def download(url: str, dest: Path, progress=None) -> None:
    """Download to dest via a temporary file; progress(done, total) may return False to cancel."""
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "ClarinetTone-updater"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress and progress(done, total) is False:
                raise InterruptedError("cancelled")
    if total and done != total:
        raise IOError("download was incomplete")
    tmp.replace(dest)


def install(new_file: Path, folder: Path) -> Path:
    """Put new_file in folder as ClarinetTone.exe.  A running copy there is
    renamed first (Windows allows renaming a running .exe, not overwriting it)."""
    target = folder / EXE_NAME
    old = folder / "ClarinetTone.old.exe"
    if target.exists():
        try:
            old.unlink()
        except OSError:
            pass
        target.replace(old)
    new_file.replace(target)
    return target


def clean_old(folder: Path) -> None:
    """Remove the copy left behind by the last update."""
    try:
        (folder / "ClarinetTone.old.exe").unlink()
    except OSError:
        pass


def launch(exe: Path) -> None:
    flags = 0x00000008 if os.name == "nt" else 0     # DETACHED_PROCESS
    # A fresh copy must not reuse this copy's unpacked files.
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("_PYI") or k.startswith("_MEI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen([str(exe)], cwd=str(exe.parent), env=env,
                     creationflags=flags, close_fds=True)
