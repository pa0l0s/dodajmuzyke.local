from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "dodajmuzyke"
    music_dir: Path = Path("/music")
    work_dir: Path = Path("/downloads")
    database_path: Path = Path("/downloads/dodajmuzyke.sqlite3")
    acoustid_api_key: str | None = None
    max_concurrent_jobs: int = 1
    musicbrainz_user_agent: str = "dodajmuzyke/1.0 (local homelab)"
    public_base_url: str = "http://dodajmuzyke.local"

    class Config:
        env_prefix = "DODAJMUZYKE_"
        env_file = ".env"


settings = Settings()
