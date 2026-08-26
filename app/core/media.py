import asyncio
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"}
ARCHIVE_EXTS = {".zip", ".rar"}


class ToolError(RuntimeError):
    pass


async def run_cmd(args: list[str], cwd: Path | None = None, timeout: int = 900) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ToolError(f"Timeout: {' '.join(args)}")
    text = out.decode(errors="replace")
    if proc.returncode != 0:
        raise ToolError(f"Command failed ({proc.returncode}): {' '.join(args)}\n{text[-4000:]}")
    return text


def check_required_tools() -> dict[str, bool]:
    tools = ["ffmpeg", "yt-dlp", "fpcalc", "unzip", "unrar"]
    return {tool: shutil.which(tool) is not None for tool in tools}


def parse_yt_dlp_json(output: str) -> dict:
    for line in reversed((output or "").splitlines()):
        text = line.strip()
        if text.startswith("{") and text.endswith("}"):
            return json.loads(text)
    return json.loads(output)


def parse_yt_dlp_json_lines(output: str) -> list[dict]:
    rows = []
    for line in (output or "").splitlines():
        text = line.strip()
        if not (text.startswith("{") and text.endswith("}")):
            continue
        rows.append(json.loads(text))
    return rows


def youtube_search_args(query: str, limit: int = 8) -> list[str]:
    return [
        "yt-dlp", f"ytsearch{limit}:{query}",
        "--flat-playlist", "--dump-json", "--skip-download", "--no-playlist",
        "--ignore-errors", "--no-warnings",
    ]


async def youtube_search(query: str, limit: int = 8) -> list[dict]:
    out = await run_cmd(youtube_search_args(query, limit), timeout=90)
    items = []
    for data in parse_yt_dlp_json_lines(out):
        items.append({
            "id": data.get("id"),
            "title": data.get("title"),
            "duration": data.get("duration"),
            "uploader": data.get("uploader"),
            "webpage_url": data.get("webpage_url"),
        })
    return items


def _youtube_source(query_or_url: str) -> str:
    return query_or_url if query_or_url.startswith(("http://", "https://")) else f"ytsearch1:{query_or_url}"


def youtube_info_args(query_or_url: str) -> list[str]:
    return [
        "yt-dlp", _youtube_source(query_or_url),
        "--dump-single-json", "--skip-download", "--no-playlist",
        "--js-runtimes", "node",
    ]


def youtube_download_args(query_or_url: str, target_dir: Path) -> list[str]:
    output_template = str(target_dir / "%(title).180B.%(ext)s")
    return [
        "yt-dlp", _youtube_source(query_or_url),
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "--no-playlist", "--js-runtimes", "node", "-o", output_template,
    ]


async def youtube_info(query_or_url: str) -> dict:
    out = await run_cmd(youtube_info_args(query_or_url), timeout=120)
    return parse_yt_dlp_json(out)


async def download_youtube_audio(query_or_url: str, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    await run_cmd(youtube_download_args(query_or_url, target_dir), timeout=1800)
    mp3s = sorted(target_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not mp3s:
        raise ToolError("yt-dlp nie zwrócił pliku MP3")
    return mp3s[0]


async def convert_to_mp3(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".mp3":
        if src != dest:
            shutil.copy2(src, dest)
        return dest
    await run_cmd(["ffmpeg", "-y", "-i", str(src), "-codec:a", "libmp3lame", "-qscale:a", "0", str(dest)], timeout=1800)
    return dest


def extract_archive(src: Path, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as zf:
            zf.extractall(dest)
    elif src.suffix.lower() == ".rar":
        subprocess.run(["unrar", "x", "-o+", str(src), str(dest)], check=True)
    else:
        return [src]
    return [p for p in dest.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS]


async def fingerprint(path: Path) -> dict | None:
    if not shutil.which("fpcalc"):
        return None
    out = await run_cmd(["fpcalc", "-json", str(path)], timeout=120)
    return json.loads(out)
