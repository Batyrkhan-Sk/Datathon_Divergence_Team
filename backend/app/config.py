"""Settings from environment variables (and the repo-root .env file, if present)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    api_key: str
    analyzer: str              # "real" | "demo" | "package.module:function"
    job_timeout_sec: float     # hard limit for one job, worker is killed past it
    load_timeout_sec: float    # limit for the worker to load the analyzer (models)
    strict_schema: bool        # output only the keys documented in the case
    storage_dir: Path
    frontend_dir: Path
    max_upload_mb: int
    ui_uploads_per_min: int
    upload_ttl_hours: float

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        e = os.environ.get
        return cls(
            api_key=e("API_KEY", "").strip(),
            analyzer=e("ANALYZER", "real").strip(),
            job_timeout_sec=float(e("JOB_TIMEOUT_SEC", "240")),
            load_timeout_sec=float(e("LOAD_TIMEOUT_SEC", "600")),
            strict_schema=_flag("STRICT_SCHEMA"),
            storage_dir=Path(e("STORAGE_DIR", str(BACKEND / "storage"))),
            frontend_dir=Path(e("FRONTEND_DIR", str(ROOT / "frontend"))),
            max_upload_mb=int(e("MAX_UPLOAD_MB", "300")),
            ui_uploads_per_min=int(e("UI_UPLOADS_PER_MIN", "5")),
            upload_ttl_hours=float(e("UPLOAD_TTL_HOURS", "24")),
        )
