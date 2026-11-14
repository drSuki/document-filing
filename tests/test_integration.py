"""End-to-end test against a real MySQL or MariaDB server.

Skipped unless DOCFILING_TEST_DB=1. To keep it from touching real data it will only
run against a database named exactly `document_filing_test`, which it drops and
recreates from schema.sql. Example:

    DOCFILING_TEST_DB=1 DB_HOST=127.0.0.1 DB_PORT=3306 DB_USER=docfiling \\
    DB_PASSWORD=... DB_NAME=document_filing_test python -m unittest tests.test_integration -v

The user needs rights on that database (and CREATE, to recreate it).
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RUN = os.environ.get("DOCFILING_TEST_DB") == "1"
TEST_DB = "document_filing_test"

if RUN and os.environ.get("DB_NAME") != TEST_DB:
    raise SystemExit(f"Refusing to run: DB_NAME must be {TEST_DB}")

import pymysql  # noqa: E402
import pymupdf  # noqa: E402

if RUN:
    from docfiling import db, service  # noqa: E402
    from docfiling.params import SettingsError  # noqa: E402

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"


def make_pdf(path: Path, text: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    doc.save(path)
    doc.close()


def gas_certificate(expiry: date, tag: str, address: str = "Sample Cottage, 2 Sample Lane") -> str:
    return (
        f"Landlord Gas Safety Record\nProperty: {address}\n"
        f"Date of inspection: 01/01/2026\nNext inspection due: {expiry:%d/%m/%Y}\n"
        f"Certificate number {tag}"
    )


def split_statements(sql: str):
    """Split on semicolons that are not inside single-quoted strings."""
    statement, quoted = [], False
    for char in sql:
        if char == "'":
            quoted = not quoted
        if char == ";" and not quoted:
            yield "".join(statement)
            statement = []
        else:
            statement.append(char)
    if "".join(statement).strip():
        yield "".join(statement)


def load_schema():
    sql = SCHEMA.read_text(encoding="utf-8").replace("document_filing", TEST_DB)
    sql = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    conn = pymysql.connect(
        host=os.environ["DB_HOST"], port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"], autocommit=True,
    )
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        for statement in split_statements(sql):
            if statement.strip():
                cur.execute(statement)
    conn.close()


@unittest.skipUnless(RUN, "set DOCFILING_TEST_DB=1 to run against a real database")
class TestAgainstRealDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_schema()
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.inbox, cls.nas = root / "inbox", root / "nas"
        cls.inbox.mkdir()
        cls.nas.mkdir()
        service.seed()
        service.save_settings({"nas_root": str(cls.nas), "inbox_dir": str(cls.inbox)})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # -- tests are numbered so they run in order, as one scenario ------------
    def test_01_schema_and_seed(self):
        with db.connection() as conn:
            rules = db.load_rules(conn)
            matching = db.load_matching(conn)
            types = {t: p for t, p in rules["types"].items()}
        self.assertIn("gas safety", types["Certificate"])
        self.assertTrue(rules["expiry_keywords"])
        self.assertEqual({p["name"] for p in matching["properties"]}, {"Example House", "Sample Cottage"})

    def test_02_seed_is_repeatable_and_keeps_edits(self):
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE classification_phrases SET weight = 99 WHERE phrase = 'gas safety'")
        service.seed()
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT weight FROM classification_phrases WHERE phrase = 'gas safety'")
            self.assertEqual(float(cur.fetchone()["weight"]), 99.0)
            cur.execute("UPDATE classification_phrases SET weight = 5 WHERE phrase = 'gas safety'")

    def test_03_settings_validation(self):
        with self.assertRaises(SettingsError):
            service.save_settings({"min_score": "abc"})
        with self.assertRaises(SettingsError):
            service.save_settings({"smtp_password": "x"})       # not editable
        with self.assertRaises(SettingsError):
            service.save_settings({"min_score": "5", "nope": "1"})
        keys = {row["setting_key"]: row["setting_value"] for row in service.editable_settings()}
        self.assertEqual(keys["min_score"], "4")                # nothing partially saved

    def test_04_dry_run_changes_nothing(self):
        make_pdf(self.inbox / "gas1.pdf", gas_certificate(date.today() + timedelta(days=10), "A1"))
        results = service.process_inbox(dry_run=True)
        self.assertEqual([r[1] for r in results], ["would file"])
        self.assertTrue((self.inbox / "gas1.pdf").exists())
        self.assertEqual(service.pending_documents(), [])

    def test_05_filing_stores_relative_path(self):
        results = service.process_inbox()
        self.assertEqual([r[1] for r in results], ["filed"])
        self.assertFalse((self.inbox / "gas1.pdf").exists())
        filed = self.nas / "Certificates" / "Sample Cottage" / "gas1.pdf"
        self.assertTrue(filed.exists())
        row = service.pending_documents()[0]
        self.assertEqual(row["relative_path"], "Certificates/Sample Cottage/gas1.pdf")
        self.assertEqual(row["property_name"], "Sample Cottage")
        self.assertEqual(row["document_type"], "Certificate")
        self.assertEqual(Path(row["nas_path"]), filed)

    def test_06_duplicate_is_moved_aside(self):
        # A duplicate is a byte-for-byte copy (a regenerated PDF has different bytes).
        shutil.copy2(self.nas / "Certificates" / "Sample Cottage" / "gas1.pdf", self.inbox / "gas1_copy.pdf")
        results = service.process_inbox()
        self.assertEqual([r[1] for r in results], ["duplicate"])
        self.assertTrue((self.inbox / "_duplicates" / "gas1_copy.pdf").exists())

    def test_07_unconfirmed_dates_do_not_alert(self):
        self.assertEqual(service.due_alerts(), [])
        self.assertEqual(service.unconfirmed_count(), 1)

    def test_08_confirm_then_alert_uses_type_lead_time(self):
        doc_id = service.pending_documents()[0]["id"]
        service.confirm(doc_id)                                  # expiry in 10 days, lead 1 month
        alerts = service.due_alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert_status"], "Alert due")
        self.assertEqual(alerts[0]["lead_months"], 1)

    def test_09_far_expiry_is_not_yet_due(self):
        # A different property, so it does not supersede the first certificate.
        make_pdf(self.inbox / "gas_far.pdf",
                 gas_certificate(date.today() + timedelta(days=400), "B2", "1 Example Street"))
        service.process_inbox()
        pending = [r for r in service.pending_documents() if r["relative_path"].endswith("gas_far.pdf")]
        self.assertEqual(pending[0]["property_name"], "Example House")
        service.confirm(pending[0]["id"])
        self.assertEqual(len(service.due_alerts()), 1)           # the far-dated one is not yet due

    def test_10_newer_confirmed_document_supersedes_older(self):
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM documents WHERE relative_path LIKE %s", ("%gas1.pdf",))
            old_id = cur.fetchone()["id"]
        make_pdf(self.inbox / "gas_new.pdf", gas_certificate(date.today() + timedelta(days=800), "C3"))
        service.process_inbox()
        new = [r for r in service.pending_documents() if r["relative_path"].endswith("gas_new.pdf")][0]
        retired = service.confirm(new["id"])
        self.assertGreaterEqual(retired, 1)
        with db.connection() as conn:
            self.assertEqual(db.get_document(conn, old_id)["superseded_by_id"], new["id"])
        self.assertEqual(service.due_alerts(), [])               # superseded no longer alerts

    def test_11_unrecognised_goes_to_review_folder(self):
        make_pdf(self.inbox / "letter.pdf", "Dear Sir, thank you for your letter.")
        service.process_inbox()
        self.assertTrue((self.nas / "Needs Review" / "letter.pdf").exists())

    def test_12_changing_nas_root_moves_every_path(self):
        new_root = self.nas.parent / "nas_moved"
        self.nas.rename(new_root)
        service.save_settings({"nas_root": str(new_root)})
        rows = service.pending_documents()
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(Path(row["nas_path"]).exists(), row["nas_path"])
        service.save_settings({"nas_root": str(self.nas)})
        self.nas = new_root.rename(self.nas)

    def test_13_blank_location_gives_clear_error(self):
        service.save_settings({"inbox_dir": ""})
        try:
            with self.assertRaises(SettingsError) as ctx:
                service.process_inbox(dry_run=True)
            self.assertIn("inbox_dir", str(ctx.exception))
        finally:
            service.save_settings({"inbox_dir": str(self.inbox)})


if __name__ == "__main__":
    unittest.main()
