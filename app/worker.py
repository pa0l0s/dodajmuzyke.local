import asyncio
import shutil
from pathlib import Path
from .core.config import settings
from .core.matching import clean_title, infer_metadata_suggestion
from .core.media import AUDIO_EXTS, ARCHIVE_EXTS, convert_to_mp3, download_youtube_audio, extract_archive, fingerprint, youtube_info
from .core.metadata import fetch_cover, lookup_by_fingerprint, lookup_by_text, write_id3
from .core.paths import destination_for_match, move_into_library
from .core.state import JobStore

store = JobStore(settings.database_path)
queue: asyncio.Queue[str] = asyncio.Queue()
worker_task: asyncio.Task | None = None


def collect_known_artists(music_dir: Path, extra: list[str] | None = None) -> list[str]:
    artists = []
    seen = set()
    for name in extra or []:
        clean = str(name or "").strip()
        if clean and clean.casefold() not in seen:
            artists.append(clean)
            seen.add(clean.casefold())
    try:
        for child in music_dir.iterdir():
            if child.is_dir() and not child.name.startswith("_") and child.name.casefold() not in seen:
                artists.append(child.name)
                seen.add(child.name.casefold())
    except OSError:
        pass
    return artists


def ensure_dirs() -> None:
    settings.music_dir.mkdir(parents=True, exist_ok=True)
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    (settings.music_dir / "_Unmatched").mkdir(parents=True, exist_ok=True)


async def start_worker() -> None:
    global worker_task
    ensure_dirs()
    if worker_task is None or worker_task.done():
        worker_task = asyncio.create_task(_worker_loop())


async def enqueue(job: dict) -> dict:
    await queue.put(job["id"])
    return job


async def _worker_loop() -> None:
    while True:
        job_id = await queue.get()
        try:
            await process_job(job_id)
        finally:
            queue.task_done()


async def process_job(job_id: str) -> None:
    job = store.get(job_id)
    try:
        store.update(job_id, status="downloading" if job["kind"] == "youtube" else "extracting", message="Przygotowanie plików roboczych")
        job_dir = settings.work_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        if job["kind"] == "youtube":
            info = None
            suggestion = None
            try:
                info = await youtube_info(job["source"])
                info["known_artists"] = collect_known_artists(settings.music_dir, extra=[info.get("uploader"), info.get("channel")])
                suggestion = infer_metadata_suggestion(info, job["source"])
                store.update(job_id, metadata={**job.get("metadata", {}), "youtube_info": _compact_youtube_info(info), "suggested": suggestion})
            except Exception as exc:
                store.update(job_id, metadata={**job.get("metadata", {}), "youtube_info_error": str(exc)})
            source = await download_youtube_audio(job["source"], job_dir)
            title = clean_title((info or {}).get("title") or source.stem)
            await _process_audio_file(job_id, source, title, suggestion=suggestion)
        else:
            uploaded = Path(job["work_path"])
            candidates = extract_archive(uploaded, job_dir / "extracted") if uploaded.suffix.lower() in ARCHIVE_EXTS else [uploaded]
            candidates = [p for p in candidates if p.suffix.lower() in AUDIO_EXTS]
            if not candidates:
                raise RuntimeError("Nie znaleziono obsługiwanych plików audio w uploadzie/archiwum")
            if len(candidates) == 1:
                await _process_audio_file(job_id, candidates[0], clean_title(candidates[0].stem))
            else:
                # Archiwum tworzy zadania podrzędne; główne zadanie raportuje rozpakowanie.
                children = []
                for p in candidates:
                    child = store.create("upload", clean_title(p.stem), work_path=str(p))
                    children.append(child["id"])
                    await enqueue(child)
                store.update(job_id, status="done", message=f"Rozpakowano archiwum i dodano {len(children)} zadań", metadata={"children": children})
    except Exception as exc:
        store.update(job_id, status="failed", message=str(exc))


async def _process_audio_file(job_id: str, source: Path, title: str, suggestion: dict | None = None) -> None:
    job_dir = settings.work_dir / job_id
    mp3_path = job_dir / f"normalized-{job_id}.mp3"
    store.update(job_id, status="converting", message="Konwersja do MP3 VBR V0")
    await convert_to_mp3(source, mp3_path)

    store.update(job_id, status="tagging", message="Fingerprint i dopasowanie MusicBrainz/AcoustID")
    fp = None
    match = None
    try:
        fp = await fingerprint(mp3_path)
        match = await lookup_by_fingerprint(fp, settings.acoustid_api_key, settings.musicbrainz_user_agent)
    except Exception as exc:
        # Fingerprint/metadane są best effort; fallback tekstowy poniżej.
        fp = {"error": str(exc)}
    if not match:
        try:
            duration = fp.get("duration") if isinstance(fp, dict) else None
            lookup_title = f"{suggestion.get('artist')} - {suggestion.get('title')}" if suggestion and suggestion.get("artist") and suggestion.get("title") else title
            match = await lookup_by_text(lookup_title, duration, settings.musicbrainz_user_agent)
        except Exception as exc:
            match = None
            fp = {**(fp or {}), "text_lookup_error": str(exc)}

    if match and match.get("confidence") in {"high", "medium"}:
        cover = await fetch_cover(match.get("release_id"))
        write_id3(mp3_path, match, cover)
        status = "done"
    else:
        usable_suggestion = suggestion and suggestion.get("artist") not in {None, "", "Unknown Artist"} and suggestion.get("title") not in {None, "", "unknown"}
        if usable_suggestion:
            match = {**suggestion, "confidence": "medium", "auto_from_youtube": True}
            write_id3(mp3_path, match, None)
            status = "done"
        else:
            if suggestion:
                write_id3(mp3_path, {**suggestion, "confidence": "low"}, None)
            status = "unmatched"

    dest = destination_for_match(settings.music_dir, match, fallback_title=title)
    final = move_into_library(mp3_path, dest)
    metadata = {**(store.get(job_id).get("metadata") or {}), "match": match, "fingerprint": fp, "clean_title": title, "suggested": suggestion}
    store.update(job_id, status=status, result_path=str(final), message="Gotowe" if status == "done" else "Brak pewnego dopasowania — plik w _Unmatched", metadata=metadata)


def _compact_youtube_info(info: dict | None) -> dict:
    if not info:
        return {}
    keys = ["id", "title", "uploader", "artist", "track", "album", "upload_date", "duration", "webpage_url"]
    return {k: info.get(k) for k in keys if info.get(k) is not None}


async def apply_manual_metadata(job_id: str, manual: dict) -> dict:
    job = store.get(job_id)
    current = Path(job["result_path"] or "")
    if not current.exists():
        raise FileNotFoundError("Nie znaleziono pliku wynikowego dla zadania")
    match = {
        "artist": manual.get("artist") or "Unknown Artist",
        "album": manual.get("album") or "Unknown Album",
        "title": manual.get("title") or job.get("title") or "Unknown",
        "year": str(manual.get("year") or "Unknown")[:4],
        "track": str(manual.get("track") or "00").zfill(2),
        "confidence": "medium",
        "manual": True,
    }
    write_id3(current, match, None)
    dest = destination_for_match(settings.music_dir, match, fallback_title=match["title"])
    final = move_into_library(current, dest)
    return store.update(job_id, status="done", result_path=str(final), message="Ręcznie otagowano i przeniesiono", metadata={**job.get("metadata", {}), "manual_match": match})
