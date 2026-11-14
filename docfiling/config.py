"""Bootstrap settings only: how to reach the database, and the SMTP password.

Everything else (locations, thresholds, classification phrases, property
matching) is held in the database; see params.py.
"""

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

    # Kept out of the database on purpose: a password in a table can be shown on a page.
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")

    # Seed files used once by `main.py seed` to load the first set of rules.
    seed_rules_file: Path = PROJECT_ROOT / "seed" / "rules.json"
    seed_matching_file: Path = PROJECT_ROOT / "seed" / "matching.json"


settings = Settings()
