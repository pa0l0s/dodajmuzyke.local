import re
import shutil
from pathlib import Path
from .matching import clean_title

FORBIDDEN = re.compile(r'[<>:"/\\|?*]+')


def safe_filename(value: str, max_len: int = 120) -> str:
    text = FORBIDDEN.sub("_", value or "unknown")
    text = re.sub(r"\s+", " ", text).strip(" ._")
    return (text or "unknown")[:max_len]


def destination_for_match(music_dir: Path, match: dict | None, fallback_title: str) -> Path:
    if match and match.get("confidence") in {"high", "medium"}:
        artist = safe_filename(match.get("artist") or "Unknown Artist")
        album = safe_filename(match.get("album") or "Unknown Album")
        title = safe_filename(match.get("title") or fallback_title)
        year = str(match.get("year") or "Unknown")[:4]
        track = str(match.get("track") or "00").zfill(2)
        return music_dir / artist / f"{album} ({year})" / f"{track} - {title}.mp3"
    return music_dir / "_Unmatched" / f"{safe_filename(clean_title(fallback_title))}.mp3"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 10000):
        candidate = path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Nie można wybrać unikalnej nazwy dla {path}")


def move_into_library(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    final = unique_path(dest)
    shutil.move(str(src), str(final))
    return final
