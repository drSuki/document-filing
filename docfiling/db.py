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


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def load_settings(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT setting_key, setting_value FROM settings")
        return {row["setting_key"]: row["setting_value"] for row in cur.fetchall()}


def list_settings(conn) -> list:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT setting_key, setting_value, description FROM settings ORDER BY setting_key"
        )
        return list(cur.fetchall())


def set_setting(conn, key: str, value: str) -> bool:
    """Update an existing setting. Returns False if the key does not exist."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM settings WHERE setting_key = %s", (key,))
        if cur.fetchone() is None:
            return False
        cur.execute("UPDATE settings SET setting_value = %s WHERE setting_key = %s", (value, key))
    return True


# ---------------------------------------------------------------------------
# Rules and matching, returned in the shape the classifier uses
# ---------------------------------------------------------------------------
def load_rules(conn) -> dict:
    rules = {"types": {}, "expiry_keywords": [], "issue_keywords": []}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT t.name, p.phrase, p.weight
               FROM classification_phrases p
               JOIN document_types t ON t.id = p.document_type_id
               WHERE p.active = 1"""
        )
        for row in cur.fetchall():
            rules["types"].setdefault(row["name"], {})[row["phrase"].lower()] = float(row["weight"])
        cur.execute(
            "SELECT phrase, pick FROM expiry_phrases WHERE active = 1 ORDER BY priority, id"
        )
        rules["expiry_keywords"] = [
            {"phrase": r["phrase"].lower(), "pick": r["pick"]} for r in cur.fetchall()
        ]
        cur.execute(
            "SELECT phrase FROM issue_date_phrases WHERE active = 1 ORDER BY priority, id"
        )
        rules["issue_keywords"] = [r["phrase"].lower() for r in cur.fetchall()]
    return rules


def load_matching(conn) -> dict:
    matching = {"properties": [], "companies": {}, "counterparties": []}
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM properties WHERE active = 1 ORDER BY id")
        by_id = {}
        for row in cur.fetchall():
            entry = {"id": row["id"], "name": row["name"], "keywords": []}
            by_id[row["id"]] = entry
            matching["properties"].append(entry)
        cur.execute("SELECT property_id, keyword FROM property_keywords")
        for row in cur.fetchall():
            if row["property_id"] in by_id:
                by_id[row["property_id"]]["keywords"].append(row["keyword"])
        cur.execute("SELECT company_code, keyword FROM company_keywords")
        for row in cur.fetchall():
            matching["companies"].setdefault(row["company_code"], []).append(row["keyword"])
        cur.execute("SELECT name FROM counterparties WHERE active = 1 ORDER BY name")
        matching["counterparties"] = [r["name"] for r in cur.fetchall()]
    return matching


def property_names(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM properties")
        return {row["id"]: row["name"] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Seeding: idempotent upserts that never delete or overwrite your own edits
# ---------------------------------------------------------------------------
def seed_rules(conn, rules: dict) -> dict:
    counts = {"classification_phrases": 0, "expiry_phrases": 0, "issue_date_phrases": 0}
    with conn.cursor() as cur:
        for type_name, phrases in rules["types"].items():
            cur.execute("SELECT id FROM document_types WHERE name = %s", (type_name,))
            row = cur.fetchone()
            if row is None:
                raise LookupError(f"Seed refers to unknown document type '{type_name}'")
            for phrase, weight in phrases.items():
                counts["classification_phrases"] += cur.execute(
                    """INSERT INTO classification_phrases (document_type_id, phrase, weight)
                       VALUES (%s, %s, %s)
                       ON DUPLICATE KEY UPDATE id = id""",
                    (row["id"], phrase.lower(), weight),
                )
        for priority, entry in enumerate(rules["expiry_keywords"], start=1):
            counts["expiry_phrases"] += cur.execute(
                """INSERT INTO expiry_phrases (phrase, pick, priority) VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE id = id""",
                (entry["phrase"].lower(), entry["pick"], priority * 10),
            )
        for priority, phrase in enumerate(rules["issue_keywords"], start=1):
            counts["issue_date_phrases"] += cur.execute(
                """INSERT INTO issue_date_phrases (phrase, priority) VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE id = id""",
                (phrase.lower(), priority * 10),
            )
    return counts


def seed_matching(conn, matching: dict) -> dict:
    counts = {"properties": 0, "property_keywords": 0, "company_keywords": 0, "counterparties": 0}
    with conn.cursor() as cur:
        for prop in matching["properties"]:
            counts["properties"] += cur.execute(
                "INSERT INTO properties (name) VALUES (%s) ON DUPLICATE KEY UPDATE id = id",
                (prop["name"],),
            )
            cur.execute("SELECT id FROM properties WHERE name = %s", (prop["name"],))
            property_id = cur.fetchone()["id"]
            for keyword in prop["keywords"]:
                counts["property_keywords"] += cur.execute(
                    """INSERT INTO property_keywords (property_id, keyword) VALUES (%s, %s)
                       ON DUPLICATE KEY UPDATE id = id""",
                    (property_id, keyword.lower()),
                )
        for code, keywords in matching["companies"].items():
            for keyword in keywords:
                counts["company_keywords"] += cur.execute(
                    """INSERT INTO company_keywords (company_code, keyword) VALUES (%s, %s)
                       ON DUPLICATE KEY UPDATE id = id""",
                    (code, keyword.lower()),
                )
        for name in matching["counterparties"]:
            counts["counterparties"] += cur.execute(
                "INSERT INTO counterparties (name) VALUES (%s) ON DUPLICATE KEY UPDATE id = id",
                (name,),
            )
    return counts


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
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
                   d.expiry_date, d.property_id, d.counterparty, d.relative_path
            FROM documents d
            JOIN document_types t ON t.id = d.document_type_id
            WHERE d.review_status = 'pending_review'
            ORDER BY d.id
            """
        )
        return list(cur.fetchall())


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
                   expiry_date, lead_months, alert_date, alert_status, relative_path
            FROM v_document_alerts
            WHERE alert_status IN ('Alert due', 'Expired')
              AND expiry_confirmed = 1
            ORDER BY expiry_date
            """
        )
        return list(cur.fetchall())


def unconfirmed_expiry_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM documents "
            "WHERE expiry_date IS NOT NULL AND expiry_confirmed = 0 "
            "AND review_status = 'pending_review'"
        )
        return cur.fetchone()["n"]
