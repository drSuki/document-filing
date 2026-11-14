"""High-level operations shared by the command line and the Django page.

Callers (main.py, and the customer-contract Documents page) use these
functions and carry no SQL or filing logic of their own.
"""

import json
from datetime import date
from typing import Optional

from . import alerts, db, filer
from .config import settings


def property_names() -> dict:
    """Map property id to name, from matching.json."""
    with open(settings.matching_file, encoding="utf-8") as handle:
        matching = json.load(handle)
    return {prop["id"]: prop["name"] for prop in matching["properties"]}


def pending_documents() -> list:
    """Documents awaiting review, with a readable property name."""
    names = property_names()
    with db.connection() as conn:
        rows = db.list_pending(conn)
    for row in rows:
        row["property_name"] = names.get(row["property_id"])
    return rows


def due_alerts() -> list:
    names = property_names()
    with db.connection() as conn:
        rows = db.due_alerts(conn)
    for row in rows:
        row["property_name"] = names.get(row["property_id"])
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
