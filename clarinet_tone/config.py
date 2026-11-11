"""Settings, exercises, reeds, and file naming."""
import json
import os
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, date
from pathlib import Path

APP_NAME = "Clarinet Tone Tracker"
SAMPLE_RATE = 48000
SUBTYPE = "PCM_24"
MIC_HINT = "snowball"


def documents_dir() -> Path:
    """The user's Documents folder (handles a relocated Documents on Windows)."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5 (Documents)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
            if buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"


SUBPATH = Path("Claude") / "Clarinet tone"


def candidate_documents() -> list[Path]:
    """Places a Documents folder may live, most likely first."""
    c = [documents_dir(), Path.home() / "Documents"]
    up = os.environ.get("USERPROFILE")
    if up:
        c += [Path(up) / "Documents", Path(up) / "OneDrive" / "Documents"]
    if os.name == "nt":
        import string
        for letter in string.ascii_uppercase[2:]:
            users = Path(f"{letter}:/Users")
            try:
                if users.is_dir():
                    c += [u / "Documents" for u in users.iterdir() if u.is_dir()]
            except OSError:
                continue
    seen, out = set(), []
    for p in c:
        k = str(p).lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def find_base_dir() -> Path | None:
    """The existing Documents\\Claude\\Clarinet tone folder, if one can be found."""
    for d in candidate_documents():
        try:
            if (d / SUBPATH).is_dir():
                return d / SUBPATH
        except OSError:
            continue
    return None


def default_base_dir() -> Path:
    return find_base_dir() or (documents_dir() / SUBPATH)


def settings_path() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home() / ".config"))
    return root / "ClarinetTone" / "settings.json"


@dataclass
class Settings:
    base_dir: str = ""
    last_reed: str = ""
    level_yellow_db: float = -6.0
    level_red_db: float = -2.0
    shortcut_made: bool = False
    hearing_aids: bool = False          # last setting of the hearing-aids switch
    metronome_on: bool = True           # click in the Bluetooth headset during takes
    headset: str = ""                   # "shokz" or "sony": Bob picks; never switched automatically
    equipment_on: bool = False          # record mouthpiece, ligature, barrel with each take
    mouthpiece: str = ""
    ligature: str = ""
    barrel: str = ""

    @property
    def recordings_dir(self) -> Path:
        return Path(self.base_dir) / "Recordings"

    @property
    def tests_dir(self) -> Path:
        return self.recordings_dir / "Tests"

    @property
    def reeds_file(self) -> Path:
        return Path(self.base_dir) / "reeds.json"

    @classmethod
    def load(cls) -> "Settings":
        p = settings_path()
        s = cls()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
            except Exception:
                pass
        if not s.base_dir or not Path(s.base_dir).is_dir():
            found = find_base_dir()
            s.base_dir = str(found) if found else ""
        return s

    def save(self) -> None:
        p = settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


@dataclass(frozen=True)
class Exercise:
    key: str          # used in file names
    title: str
    tempo: str        # what the metronome is set to, in words
    bpm: int = 0      # 0 = no metronome
    beats: int = 0    # beats per bar; the first beat of each bar is accented


def long_tone_for(day: date) -> Exercise:
    if day.day % 2:
        return Exercise("long-tone-chalumeau", "Long tones, chalumeau (odd day)", "88 bpm, 4/4", 88, 4)
    return Exercise("long-tone-clarion", "Long tones, clarion (even day)", "88 bpm, 4/4", 88, 4)


LEGATO = Exercise("legato", "Legato warm-up", "88 bpm, 2/4", 88, 2)
REGISTER = Exercise("register", "Register key / embouchure", "60 bpm, 2/4", 60, 2)
TUNING = Exercise("tuning", "Tuning pattern", "no metronome")

# Headsets for the metronome: key -> (button label, part of the name Windows shows)
HEADSETS = {"shokz": ("Shokz", "openrun"), "sony": ("Sony", "wh-ch720n")}

# Written notes of the tuning pattern, slurred, in order (Bob, 2026-11-10).
TUNING_PATTERN = ["C4", "G5", "C5", "C4", "G5", "E6"]


def exercises_for(day: date) -> list[Exercise]:
    return [long_tone_for(day), LEGATO, REGISTER, TUNING]


TEST = Exercise("test", "Test", "whatever the test needs")


def test_key(description: str) -> str:
    """File-name key for a test take, e.g. "tuner check" -> "test-tuner-check"."""
    words = re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")
    return f"test-{words[:40].rstrip('-')}" if words else "test"


# ---------------------------------------------------------------- reeds

DEFAULT_BRAND = "Vandoren"
DEFAULT_MODEL = "56 Rue Lepic"
DEFAULT_STRENGTH = "3"


@dataclass
class Reed:
    started: str            # ISO date written on the reed, e.g. 2026-08-04
    dots: int               # 1, 2 or 3 dots on the heel
    brand: str = DEFAULT_BRAND
    model: str = DEFAULT_MODEL
    strength: str = DEFAULT_STRENGTH
    notes: str = ""
    retired: bool = False
    adjustments: list = field(default_factory=list)   # [{"date":..., "what":...}]

    @property
    def label(self) -> str:
        d = date.fromisoformat(self.started)
        return f"{d.month:02d}{d.day:02d}-{self.dots}"

    def age_days(self, today: date | None = None) -> int:
        """Days since the date written on the reed."""
        return ((today or date.today()) - date.fromisoformat(self.started)).days

    @property
    def display(self) -> str:
        d = date.fromisoformat(self.started)
        return (f"{d.month}/{d.day}/{d.year}   {self.brand} {self.model} "
                f"#{self.strength}   {'•' * self.dots}")


def load_reeds(path: Path) -> list[Reed]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        reeds = [Reed(**r) for r in data]
    except Exception:
        return []
    if _undo_dot_changes(reeds):
        save_reeds(path, reeds)
    return reeds


_DOT_CHANGE = re.compile(r"^dots (\d) to (\d)$")


def _undo_dot_changes(reeds: list[Reed]) -> bool:
    """Build 11d1322 changed a reed's dots in place, which moved one reed's notes
    onto another reed.  Put each such reed back to its original dots."""
    changed = False
    for r in reeds:
        moves = [a for a in r.adjustments
                 if isinstance(a, dict) and _DOT_CHANGE.match(str(a.get("what", "")))]
        if not moves:
            continue
        original = int(_DOT_CHANGE.match(moves[0]["what"]).group(1))
        label = Reed(started=r.started, dots=original).label
        if any(x is not r and x.label == label for x in reeds):
            continue
        r.dots = original
        r.adjustments = [a for a in r.adjustments if a not in moves]
        changed = True
    return changed


def save_reeds(path: Path, reeds: list[Reed]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(r) for r in reeds], indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- file names

_SAFE = re.compile(r"[^A-Za-z0-9-]")


def recording_name(start: datetime, reed_label: str, exercise_key: str) -> str:
    reed = _SAFE.sub("", reed_label) or "unknown"
    return f"{start:%Y-%m-%d_%H%M}_reed-{reed}_{exercise_key}.wav"


def unique_path(folder: Path, name: str) -> Path:
    p = folder / name
    n = 2
    while p.exists():
        p = folder / f"{Path(name).stem}_{n}.wav"
        n += 1
    return p


# ---------------------------------------------------------------- Explorer view

_DESKTOP_INI = "[ViewState]\r\nMode=\r\nVid=\r\nFolderType=Generic\r\n"


def set_general_view(folder: Path) -> None:
    """Ask Windows Explorer to show this folder as "General items"
    (Name, Date modified, Type, Size) rather than as music."""
    if os.name != "nt":
        return
    ini = folder / "desktop.ini"
    try:
        if ini.exists():
            return
        ini.write_text(_DESKTOP_INI, encoding="utf-8")
        import ctypes
        k = ctypes.windll.kernel32
        HIDDEN, SYSTEM, READONLY = 0x2, 0x4, 0x1
        k.SetFileAttributesW(str(ini), HIDDEN | SYSTEM)
        # Explorer reads desktop.ini only when the folder is marked read-only or system.
        attrs = k.GetFileAttributesW(str(folder))
        if attrs != -1 and attrs != 0xFFFFFFFF:
            k.SetFileAttributesW(str(folder), attrs | READONLY)
    except Exception:
        pass
