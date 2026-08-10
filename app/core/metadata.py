import httpx
from pathlib import Path
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TRCK, TDRC, ID3NoHeaderError
from .matching import split_artist_title, text_score, duration_score, confidence_from_scores

MB = "https://musicbrainz.org/ws/2"
CAA = "https://coverartarchive.org"
ACOUSTID = "https://api.acoustid.org/v2/lookup"


def _headers(user_agent: str) -> dict:
    return {"User-Agent": user_agent, "Accept": "application/json"}


async def lookup_by_fingerprint(fp: dict, api_key: str | None, user_agent: str) -> dict | None:
    if not fp or not api_key:
        return None
    params = {
        "client": api_key,
        "meta": "recordings releases releasegroups artists",
        "duration": fp.get("duration"),
        "fingerprint": fp.get("fingerprint"),
    }
    async with httpx.AsyncClient(timeout=30, headers=_headers(user_agent)) as client:
        r = await client.get(ACOUSTID, params=params)
        r.raise_for_status()
        data = r.json()
    results = data.get("results") or []
    if not results:
        return None
    best = max(results, key=lambda x: x.get("score", 0))
    recordings = best.get("recordings") or []
    if not recordings:
        return None
    return _recording_to_match(recordings[0], fingerprint_score=float(best.get("score", 0)), source_duration=fp.get("duration"))


async def lookup_by_text(title: str, source_duration: float | None, user_agent: str) -> dict | None:
    artist, track = split_artist_title(title)
    query = f'artist:"{artist}" AND recording:"{track}"' if artist else f'recording:"{track}"'
    params = {"query": query, "fmt": "json", "limit": 5, "inc": "artists+releases"}
    async with httpx.AsyncClient(timeout=30, headers=_headers(user_agent)) as client:
        r = await client.get(f"{MB}/recording", params=params)
        r.raise_for_status()
        data = r.json()
    recs = data.get("recordings") or []
    if not recs:
        return None

    def score(rec):
        artist_credit = " ".join(a.get("artist", {}).get("name", "") for a in rec.get("artist-credit", []) if isinstance(a, dict))
        candidate = f"{artist_credit} - {rec.get('title', '')}" if artist_credit else rec.get("title", "")
        d = (int(rec.get("length", 0)) / 1000.0) if rec.get("length") else None
        return text_score(title, candidate) * 0.75 + duration_score(source_duration, d) * 0.25

    best = max(recs, key=score)
    return _recording_to_match(best, fingerprint_score=None, source_duration=source_duration, original_query=title)


def _recording_to_match(rec: dict, fingerprint_score: float | None, source_duration: float | None = None, original_query: str | None = None) -> dict:
    artists = [a.get("artist", {}).get("name") for a in rec.get("artist-credit", []) if isinstance(a, dict)]
    artist = ", ".join([a for a in artists if a]) or "Unknown Artist"
    releases = rec.get("releases") or []
    release = releases[0] if releases else {}
    date = release.get("date") or rec.get("first-release-date") or ""
    year = date[:4] if date else "Unknown"
    title = rec.get("title") or original_query or "Unknown"
    duration = (int(rec.get("length", 0)) / 1000.0) if rec.get("length") else None
    text = text_score(original_query or f"{artist} - {title}", f"{artist} - {title}")
    dur = duration_score(source_duration, duration)
    conf = confidence_from_scores(fingerprint_score, text, dur)
    media = release.get("media") or []
    track_num = "00"
    if media and media[0].get("tracks"):
        for t in media[0].get("tracks"):
            if t.get("recording", {}).get("id") == rec.get("id") or t.get("title") == title:
                track_num = str(t.get("number") or t.get("position") or "00")
                break
    return {
        "recording_id": rec.get("id"),
        "release_id": release.get("id"),
        "artist": artist,
        "album": release.get("title") or "Unknown Album",
        "title": title,
        "year": year,
        "track": track_num,
        "confidence": conf,
        "scores": {"fingerprint": fingerprint_score, "text": text, "duration": dur},
    }


async def fetch_cover(release_id: str | None) -> bytes | None:
    if not release_id:
        return None
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{CAA}/release/{release_id}/front-250")
        if r.status_code != 200:
            return None
        return r.content


def write_id3(path: Path, match: dict, cover: bytes | None = None) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags["TPE1"] = TPE1(encoding=3, text=match.get("artist", ""))
    tags["TALB"] = TALB(encoding=3, text=match.get("album", ""))
    tags["TIT2"] = TIT2(encoding=3, text=match.get("title", ""))
    tags["TRCK"] = TRCK(encoding=3, text=str(match.get("track", "")))
    tags["TDRC"] = TDRC(encoding=3, text=str(match.get("year", "")))
    if cover:
        tags.delall("APIC")
        tags["APIC"] = APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover)
    tags.save(path, v2_version=3)
