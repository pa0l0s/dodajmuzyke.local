import re
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlparse

NOISE_PATTERNS = [
    r"\bofficial\s+(music\s+)?video\b",
    r"\bofficial\s+audio\b",
    r"\boficjaln[ay]\b",
    r"\boficjalna\s+taśma\s+vhs\b",
    r"\blyric\s+video\b",
    r"\blyrics\b",
    r"\bremaster(ed)?\b",
    r"\b4k\b",
    r"\bhd\b",
    r"\buhd\b",
    r"\bvisuali[sz]er\b",
    r"\bvideo\s+clip\b",
]
BRACKETED = re.compile(r"\[[^\]]*\]|\([^)]*\)")
SPACES = re.compile(r"\s+")


def clean_title(value: str) -> str:
    text = value or "unknown"
    text = text.replace("_", " ")
    text = BRACKETED.sub(lambda m: " " if any(re.search(p, m.group(0), re.I) for p in NOISE_PATTERNS) or re.search(r"\b(4k|hd|uhd)\b", m.group(0), re.I) else m.group(0), text)
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.I)
    text = re.sub(r"\s+-\s+Topic$", "", text, flags=re.I)
    text = re.sub(r"\b\d{3,4}p\b", " ", text, flags=re.I)
    text = re.sub(r"#\w+", " ", text, flags=re.I)
    text = SPACES.sub(" ", text).strip(" -–—|•\t\n\"'„”‚’“”")
    return text or "unknown"


def _norm_name(value: str) -> str:
    return clean_title(value).casefold()


def split_artist_title(text: str, known_artists: list[str] | None = None) -> tuple[str | None, str]:
    cleaned = clean_title(text)
    known = {_norm_name(a) for a in (known_artists or []) if a}
    for sep in [" - ", " – ", " — "]:
        if sep in cleaned:
            left, right = cleaned.split(sep, 1)
            left_clean, right_clean = clean_title(left), clean_title(right)
            if known:
                left_known = _norm_name(left_clean) in known
                right_known = _norm_name(right_clean) in known
                if right_known and not left_known:
                    return right_clean or None, left_clean or cleaned
                if left_known and not right_known:
                    return left_clean or None, right_clean or cleaned
            if re.match(r"^\s*[\"'„”‚’“].+[\"'„”‚’“]\s*$", left) or left.strip().endswith(("\"", "'", "„", "”", "‚", "’", "“")):
                return right_clean or None, left_clean
            return left_clean or None, right_clean or cleaned
    return None, cleaned


def youtube_video_key(value: str) -> str:
    """Return a stable duplicate key for YouTube URLs or search text."""
    raw = (value or "").strip()
    parsed = urlparse(raw)
    host = parsed.netloc.lower().removeprefix("www.")
    video_id = None
    if host in {"youtu.be", "youtube.com", "m.youtube.com", "music.youtube.com"}:
        if host == "youtu.be":
            video_id = parsed.path.strip("/").split("/", 1)[0]
        elif parsed.path == "/watch":
            video_id = (parse_qs(parsed.query).get("v") or [None])[0]
        elif parsed.path.startswith(("/embed/", "/shorts/", "/live/")):
            parts = [p for p in parsed.path.split("/") if p]
            video_id = parts[1] if len(parts) > 1 else None
    if video_id:
        return f"youtube:{video_id}"
    return "search:" + SPACES.sub(" ", raw.lower()).strip()


def _first_line_value(description: str, labels: tuple[str, ...]) -> str | None:
    for line in (description or "").splitlines():
        text = line.strip(" \t-–—•")
        for label in labels:
            m = re.match(rf"^{re.escape(label)}\s*[:\-–—]\s*(.+)$", text, flags=re.I)
            if m:
                return m.group(1).strip()
    return None


def _youtube_music_block(description: str) -> dict:
    lines = [ln.strip() for ln in (description or "").splitlines()]
    for idx, line in enumerate(lines):
        if line.lower() != "muzyka":
            continue
        candidates = [ln for ln in lines[idx + 1:] if ln and not re.match(r"^\d+\s+utw", ln, flags=re.I)]
        if len(candidates) >= 2:
            result = {"title": candidates[0], "artist": candidates[1]}
            if len(candidates) >= 3 and candidates[2].lower() != candidates[0].lower():
                result["album"] = candidates[2]
            return result
    return {}


def _premiere_year(description: str) -> str | None:
    months = "sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paź|paz|lis|gru"
    m = re.search(rf"\b(?:data\s+premiery|premiera)\s*:\s*\d{{1,2}}\s+(?:{months})\w*\s+((?:19|20)\d{{2}})\b", description or "", flags=re.I)
    return m.group(1) if m else None


def infer_metadata_suggestion(info: dict | None, fallback_title: str) -> dict:
    """Best-effort manual form defaults from yt-dlp JSON/title/description."""
    info = info or {}
    description = info.get("description") or ""
    raw_title = info.get("track") or info.get("title") or fallback_title or "unknown"
    known_artists = info.get("known_artists") or []
    music_block = _youtube_music_block(description)
    title = music_block.get("title") or _first_line_value(description, ("title", "tytuł", "utwór", "song"))
    artist = music_block.get("artist") or _first_line_value(description, ("artist", "artysta", "wykonawca", "performer", "twórcy", "tworca", "twórca", "creator", "creators"))
    album = music_block.get("album") or _first_line_value(description, ("album", "release"))
    track = _first_line_value(description, ("track", "track no", "nr", "numer"))
    year = _first_line_value(description, ("year", "rok", "released"))

    if not artist:
        artist = info.get("artist") or info.get("creator") or None
    if not title:
        split_artist, split_title = split_artist_title(raw_title, known_artists=known_artists)
        artist = artist or split_artist or info.get("uploader") or "Unknown Artist"
        title = split_title
    if not album:
        album = info.get("album") or "Unknown Album"

    if not year:
        date = str(info.get("release_date") or info.get("upload_date") or "")
        year = date[:4] if len(date) >= 4 else "Unknown"
    if not year or year == "Unknown":
        year = _premiere_year(description) or year
    title_year = re.search(r"\b(19\d{2}|20\d{2})\b", raw_title)
    if (not year or year == "Unknown") and title_year:
        year = title_year.group(1)
    if title_year:
        title = re.sub(r"\s*[\[(]?\b(19\d{2}|20\d{2})\b[\])] ?", " ", title).strip()
    title = clean_title(title)
    if track:
        digits = re.search(r"\d+", str(track))
        track = digits.group(0).zfill(2) if digits else "00"
    else:
        track = "00"
    return {
        "artist": artist or "Unknown Artist",
        "album": album or "Unknown Album",
        "title": title or clean_title(fallback_title),
        "year": str(year)[:4] if re.match(r"^(19|20)\d{2}$", str(year or "")) else "Unknown",
        "track": track,
        "source": "youtube-info",
    }


def text_score(query: str, candidate: str) -> float:
    return SequenceMatcher(None, clean_title(query).lower(), clean_title(candidate).lower()).ratio()


def duration_score(source_seconds: float | None, candidate_seconds: float | None) -> float:
    if not source_seconds or not candidate_seconds:
        return 0.75
    diff = abs(float(source_seconds) - float(candidate_seconds))
    if diff <= 5:
        return 1.0
    return max(0.0, 1.0 - ((diff - 5.0) / 65.0))


def confidence_from_scores(fingerprint: float | None, text: float, duration: float) -> str:
    fp = fingerprint if fingerprint is not None else 0.0
    score = max(fp * 0.7 + duration * 0.3, text * 0.75 + duration * 0.25)
    if score >= 0.82:
        return "high"
    if score >= 0.68:
        return "medium"
    return "low"
