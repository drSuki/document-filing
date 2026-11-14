"""High-level operations shared by the command line and the Django page.

Callers (main.py, and the customer-contract Documents page) use these
functions and carry no SQL or filing logic of their own. Rows returned for
display carry a full `nas_path`, built from the nas_root setting and the stored
relative path.
"""

from datetime import date
from pathlib import Path
from typing import Optional

from . import alerts, db, filer, params as params_module
from .params import SettingsError

# Settings a person may change from the Documents page. The tool's own locations,
# thresholds and alert addresses; nothing that holds a secret.
EDITABLE_SETTINGS = (
    "nas_root", "inbox_dir", "min_score", "min_margin",
    "tesseract_cmd", "smtp_host", "smtp_port", "smtp_user", "alert_from", "alert_to",
)


def _full_path(nas_root: str, relative: str) -> str:
    return str(Path(nas_root) / relative) if nas_root else relative


def pending_documents() -> list:
    """Documents awaiting review, with a readable property name and full path."""
    with db.connection() as conn:
        rows = db.list_pending(conn)
        names = db.property_names(conn)
        nas_root = db.load_settings(conn).get("nas_root", "")
    for row in rows:
        row["property_name"] = names.get(row["property_id"])
        row["nas_path"] = _full_path(nas_root, row["relative_path"])
    return rows


def due_alerts() -> list:
    with db.connection() as conn:
        rows = db.due_alerts(conn)
        names = db.property_names(conn)
        nas_root = db.load_settings(conn).get("nas_root", "")
    for row in rows:
        row["property_name"] = names.get(row["property_id"])
        row["nas_path"] = _full_path(nas_root, row["relative_path"])
    return rows


def unconfirmed_count() -> int:
    with db.connection() as conn:
        return db.unconfirmed_expiry_count(conn)


def confirm(doc_id: int, expiry: Optional[date] = None) -> int:
    """Confirm a document, optionally correcting its expiry date, and retire any
    older document it replaces. Returns the number of documents superseded."""
    with db.connection() as conn:
        if db.get_document(conn, doc_id) is None:
            raise LookupError(f"No document with id {doc_id}")
        db.confirm_document(conn, doc_id, expiry)
        doc = db.get_document(conn, doc_id)
        return db.supersede_older(conn, doc)


def reject(doc_id: int) -> None:
    with db.connection() as conn:
        if db.get_document(conn, doc_id) is None:
            raise LookupError(f"No document with id {doc_id}")
        db.reject_document(conn, doc_id)


def process_inbox(dry_run: bool = False) -> list:
    return filer.process_inbox(dry_run=dry_run)


def alert_summary() -> str:
    return alerts.run_alerts(send=False)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def editable_settings() -> list:
    """Current values of the settings that may be edited, in a fixed order."""
    with db.connection() as conn:
        rows = {row["setting_key"]: row for row in db.list_settings(conn)}
    return [rows[key] for key in EDITABLE_SETTINGS if key in rows]


def save_settings(values: dict) -> list:
    """Validate and save the given settings. Nothing is saved unless every value is
    valid. Returns the keys that were changed."""
    cleaned = {}
    for key, value in values.items():
        if key not in EDITABLE_SETTINGS:
            raise SettingsError(f"'{key}' cannot be edited")
        cleaned[key] = params_module.validate_setting(key, value)

    changed = []
    with db.connection() as conn:
        current = db.load_settings(conn)
        for key, value in cleaned.items():
            if current.get(key) != value:
                if not db.set_setting(conn, key, value):
                    raise SettingsError(f"Unknown setting '{key}'")
                changed.append(key)
    return changed


def seed(rules: bool = True, matching: bool = True) -> dict:
    """Load the starting rules and matching from the seed files. Safe to repeat:
    existing rows are left as they are and nothing is deleted."""
    counts = {}
    with db.connection() as conn:
        if rules:
            counts.update(db.seed_rules(conn, params_module.load_seed_rules()))
        if matching:
            counts.update(db.seed_matching(conn, params_module.load_seed_matching()))
    return counts
