"""MySQL access. All SQL lives here."""

from contextlib import contextmanager
from datetime import date
from typing import Optional

import pymysql
import pymysql.cursors

from .config import settings


@contextmanager
def connection():
    conn = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_type(conn, name: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, has_expiry, nas_subfolder FROM document_types WHERE name = %s",
            (name,),
        )
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"Document type '{name}' is not in document_types")
    return row


def hash_exists(conn, file_hash: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM documents WHERE file_hash = %s", (file_hash,))
        return cur.fetchone() is not None


def insert_document(conn, **fields) -> int:
    columns = ", ".join(fields)
    placeholders = ", ".join(["%s"] * len(fields))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO documents ({columns}) VALUES ({placeholders})",
            tuple(fields.values()),
        )
        return cur.lastrowid


def get_document(conn, doc_id: int) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM documents WHERE id = %s", (doc_id,))
        return cur.fetchone()


def list_pending(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.id, t.name AS document_type, d.classification_score,
                   d.expiry_date, d.property_id, d.counterparty, d.nas_path
            FROM documents d
            JOIN document_types t ON t.id = d.document_type_id
            WHERE d.review_status = 'pending_review'
            ORDER BY d.id
            """
        )
        return cur.fetchall()


def confirm_document(conn, doc_id: int, expiry: Optional[date]) -> None:
    with conn.cursor() as cur:
        if expiry is not None:
            cur.execute(
                """UPDATE documents
                   SET expiry_date = %s, expiry_confirmed = 1, review_status = 'confirmed'
                   WHERE id = %s""",
                (expiry, doc_id),
            )
        else:
            cur.execute(
                """UPDATE documents
                   SET expiry_confirmed = IF(expiry_date IS NULL, 0, 1),
                       review_status = 'confirmed'
                   WHERE id = %s""",
                (doc_id,),
            )


def reject_document(conn, doc_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET review_status = 'rejected' WHERE id = %s", (doc_id,)
        )


def supersede_older(conn, doc: dict) -> int:
    """Mark older documents of the same type, property, company and counterparty
    as superseded by this one. Runs only for confirmed documents that have a
    property and an expiry date, so a misread date cannot retire a good record."""
    if doc["property_id"] is None or doc["expiry_date"] is None:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE documents
            SET superseded_by_id = %s
            WHERE id <> %s
              AND superseded_by_id IS NULL
              AND document_type_id = %s
              AND property_id = %s
              AND company_code <=> %s
              AND counterparty <=> %s
              AND expiry_date IS NOT NULL
              AND expiry_date < %s
            """,
            (
                doc["id"], doc["id"], doc["document_type_id"], doc["property_id"],
                doc["company_code"], doc["counterparty"], doc["expiry_date"],
            ),
        )
        return cur.rowcount


def due_alerts(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, document_type, property_id, company_code, counterparty,
                   expiry_date, lead_months, alert_date, alert_status, nas_path
            FROM v_document_alerts
            WHERE alert_status IN ('Alert due', 'Expired')
              AND expiry_confirmed = 1
            ORDER BY expiry_date
            """
        )
        return cur.fetchall()


def unconfirmed_expiry_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM documents "
            "WHERE expiry_date IS NOT NULL AND expiry_confirmed = 0 "
            "AND review_status = 'pending_review'"
        )
        return cur.fetchone()["n"]
