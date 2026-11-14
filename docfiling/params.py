"""Parameters, loaded from the database once per run.

Only the database connection (and the SMTP password) come from .env; see config.py.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import db
from .config import settings as bootstrap


class SettingsError(Exception):
    """A required setting is missing or invalid."""


NUMERIC_SETTINGS = {"min_score": float, "min_margin": float, "smtp_port": int}


@dataclass
class Params:
    nas_root: Path
    inbox_dir: Path
    min_score: float
    min_margin: float
    tesseract_cmd: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    alert_from: str
    alert_to: str
    rules: dict = field(default_factory=dict)
    matching: dict = field(default_factory=dict)


def validate_setting(key: str, value: str) -> str:
    """Return a cleaned value or raise SettingsError. Used before any save."""
    value = (value or "").strip()
    if key in NUMERIC_SETTINGS:
        try:
            number = NUMERIC_SETTINGS[key](value)
        except ValueError:
            raise SettingsError(f"{key} must be a number")
        if number < 0:
            raise SettingsError(f"{key} cannot be negative")
    return value


def build_params(conn) -> Params:
    values = db.load_settings(conn)

    def text(key: str) -> str:
        return (values.get(key) or "").strip()

    try:
        numbers = {key: kind(text(key) or 0) for key, kind in NUMERIC_SETTINGS.items()}
    except ValueError as error:
        raise SettingsError(f"A numeric setting is invalid: {error}")

    return Params(
        nas_root=Path(text("nas_root")) if text("nas_root") else Path(),
        inbox_dir=Path(text("inbox_dir")) if text("inbox_dir") else Path(),
        min_score=numbers["min_score"],
        min_margin=numbers["min_margin"],
        tesseract_cmd=text("tesseract_cmd"),
        smtp_host=text("smtp_host"),
        smtp_port=int(numbers["smtp_port"]) or 587,
        smtp_user=text("smtp_user"),
        smtp_password=bootstrap.smtp_password,
        alert_from=text("alert_from"),
        alert_to=text("alert_to"),
        rules=db.load_rules(conn),
        matching=db.load_matching(conn),
    )


def require_locations(params: Params) -> None:
    """Filing needs both locations; give a clear message rather than a path error."""
    missing = [
        name for name, value in (("nas_root", params.nas_root), ("inbox_dir", params.inbox_dir))
        if str(value) in ("", ".")
    ]
    if missing:
        raise SettingsError(
            "These settings are empty: " + ", ".join(missing)
            + ". Set them with `python main.py set <key> <value>` or on the Documents page."
        )
    if not params.rules.get("types"):
        raise SettingsError("No classification phrases are loaded. Run `python main.py seed` first.")


def load_seed_rules() -> dict:
    with open(bootstrap.seed_rules_file, encoding="utf-8") as handle:
        return json.load(handle)


def load_seed_matching() -> dict:
    with open(bootstrap.seed_matching_file, encoding="utf-8") as handle:
        return json.load(handle)
