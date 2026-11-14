"""Settings, read from environment variables or a .env file in the project root."""

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Minimal .env reader, so no extra dependency is needed."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    db_host: str = os.environ.get("DB_HOST", "localhost")
    db_port: int = int(os.environ.get("DB_PORT", "3306"))
    db_user: str = os.environ.get("DB_USER", "")
    db_password: str = os.environ.get("DB_PASSWORD", "")
    db_name: str = os.environ.get("DB_NAME", "document_filing")

    inbox_dir: Path = Path(os.environ.get("INBOX_DIR", "./inbox"))
    nas_root: Path = Path(os.environ.get("NAS_ROOT", "./nas"))

    min_score: float = float(os.environ.get("MIN_SCORE", "4"))
    min_margin: float = float(os.environ.get("MIN_MARGIN", "2"))

    tesseract_cmd: str = os.environ.get("TESSERACT_CMD", "")

    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    alert_from: str = os.environ.get("ALERT_FROM", "")
    alert_to: str = os.environ.get("ALERT_TO", "")

    rules_file: Path = PROJECT_ROOT / "rules.json"
    matching_file: Path = PROJECT_ROOT / "matching.json"


settings = Settings()
