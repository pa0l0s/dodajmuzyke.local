import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.lock = Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT,
                    source TEXT,
                    work_path TEXT,
                    result_path TEXT,
                    message TEXT,
                    metadata TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)

    def create(self, kind: str, title: str, source: str | None = None, work_path: str | None = None, metadata: dict | None = None) -> dict:
        job = {
            "id": uuid4().hex,
            "kind": kind,
            "status": "queued",
            "title": title,
            "source": source,
            "work_path": work_path,
            "result_path": None,
            "message": "Oczekuje w kolejce",
            "metadata": metadata or {},
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        with self.lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs VALUES(:id,:kind,:status,:title,:source,:work_path,:result_path,:message,:metadata,:created_at,:updated_at)",
                {**job, "metadata": json.dumps(job["metadata"])},
            )
        return job

    def find_by_youtube_key(self, youtube_key: str) -> dict | None:
        if not youtube_key:
            return None
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE kind='youtube' ORDER BY created_at DESC LIMIT 500").fetchall()
        matches = []
        for row in rows:
            job = self._row(row)
            source = job.get("source") or ""
            if job.get("metadata", {}).get("youtube_key") == youtube_key or (youtube_key.startswith("youtube:") and youtube_key.split(":", 1)[1] in source):
                matches.append(job)
        if not matches:
            return None
        def rank(job: dict):
            path = job.get("result_path") or ""
            duplicate_suffix = 1 if re.search(r" \(\d+\)\.mp3$", path) else 0
            failed = 1 if job.get("status") == "failed" else 0
            return (failed, duplicate_suffix, job.get("created_at") or "")
        return sorted(matches, key=rank)[0]

    def delete(self, job_id: str) -> bool:
        with self.lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            return cur.rowcount > 0

    def update(self, job_id: str, **fields) -> dict:
        fields["updated_at"] = now_iso()
        if "metadata" in fields:
            fields["metadata"] = json.dumps(fields["metadata"], ensure_ascii=False)
        assignments = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [job_id]
        with self.lock, self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {assignments} WHERE id=?", values)
        return self.get(job_id)

    def get(self, job_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return self._row(row)

    def list(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def _row(self, row) -> dict:
        data = dict(row)
        data["metadata"] = json.loads(data.get("metadata") or "{}")
        return data
