import shutil
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .core.config import settings
from .core.media import AUDIO_EXTS, ARCHIVE_EXTS, ToolError, check_required_tools, youtube_search
from .core.matching import youtube_video_key
from .worker import apply_manual_metadata, enqueue, start_worker, store

app = FastAPI(title="dodajmuzyke", version="1.0.0")
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


class YoutubeRequest(BaseModel):
    query: str


class ManualMetadata(BaseModel):
    artist: str
    title: str
    album: str = "Unknown Album"
    year: str = "Unknown"
    track: str = "00"


@app.on_event("startup")
async def startup_event():
    await start_worker()


@app.get("/")
async def index():
    return FileResponse(static_dir / "index.html")


@app.get("/healthz")
async def healthz():
    tools = check_required_tools()
    return {"ok": all(tools.values()), "tools": tools, "music_dir": str(settings.music_dir), "work_dir": str(settings.work_dir)}


@app.get("/api/search")
async def api_search(q: str, limit: int = 8):
    if not q.strip():
        raise HTTPException(400, "Podaj zapytanie")
    try:
        return {"items": await youtube_search(q, min(max(limit, 1), 10))}
    except ToolError as exc:
        raise HTTPException(502, f"Błąd wyszukiwania YouTube: {exc}")


@app.post("/api/youtube")
async def create_youtube_job(req: YoutubeRequest):
    if not req.query.strip():
        raise HTTPException(400, "Podaj nazwę lub URL")
    source = req.query.strip()
    key = youtube_video_key(source)
    existing = store.find_by_youtube_key(key)
    if existing and existing.get("status") not in {"failed", "deleted"}:
        return {**existing, "duplicate": True, "message": "Ten utwór jest już w kolejce albo bibliotece"}
    job = store.create("youtube", source, source=source, metadata={"youtube_key": key})
    return await enqueue(job)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "upload.bin").suffix.lower()
    if suffix not in AUDIO_EXTS and suffix not in ARCHIVE_EXTS:
        raise HTTPException(400, "Obsługiwane: mp3, wav, flac, m4a, zip, rar")
    upload_dir = settings.work_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{uuid4().hex}-{Path(file.filename or 'upload').name}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    job = store.create("upload", file.filename or dest.name, work_path=str(dest))
    return await enqueue(job)


@app.get("/api/jobs")
async def list_jobs():
    return {"items": store.list()}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    try:
        return store.get(job_id)
    except KeyError:
        raise HTTPException(404, "Nie znaleziono zadania")


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(404, "Nie znaleziono zadania")
    if job.get("status") in {"downloading", "extracting", "converting", "tagging"}:
        raise HTTPException(409, "Nie można usunąć zadania w trakcie przetwarzania")
    store.delete(job_id)
    return {"ok": True, "id": job_id}


@app.post("/api/jobs/{job_id}/manual")
async def manual_match(job_id: str, data: ManualMetadata):
    try:
        return await apply_manual_metadata(job_id, data.model_dump())
    except KeyError:
        raise HTTPException(404, "Nie znaleziono zadania")
    except Exception as exc:
        raise HTTPException(400, str(exc))
