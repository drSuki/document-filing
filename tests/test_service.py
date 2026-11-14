"""Tests for the service layer, using a stubbed database module."""

import contextlib
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docfiling import db, service


class FakeDb:
    def __init__(self):
        self.docs = {
            1: {"id": 1, "document_type_id": 2, "property_id": 2, "company_code": None,
                "counterparty": None, "expiry_date": date(2027, 9, 11)},
        }
        self.calls = []

    def install(self):
        @contextlib.contextmanager
        def fake_connection():
            yield object()

        db.connection = fake_connection
        db.get_document = lambda conn, doc_id: self.docs.get(doc_id)
        db.confirm_document = lambda conn, doc_id, expiry: self.calls.append(("confirm", doc_id, expiry))
        db.reject_document = lambda conn, doc_id: self.calls.append(("reject", doc_id))
        db.supersede_older = lambda conn, doc: 3
        db.list_pending = lambda conn: [
            {"id": 1, "document_type": "Certificate", "classification_score": 12,
             "expiry_date": date(2027, 9, 11), "property_id": 2, "counterparty": None,
             "nas_path": "x.pdf"},
        ]


class TestService(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDb()
        self.fake.install()

    def test_property_names_come_from_matching_file(self):
        self.assertEqual(service.property_names()[1], "Example House")

    def test_pending_documents_get_property_name(self):
        rows = service.pending_documents()
        self.assertEqual(rows[0]["property_name"], "Sample Cottage")

    def test_confirm_returns_superseded_count(self):
        self.assertEqual(service.confirm(1, date(2027, 9, 30)), 3)
        self.assertIn(("confirm", 1, date(2027, 9, 30)), self.fake.calls)

    def test_confirm_unknown_document(self):
        with self.assertRaises(LookupError):
            service.confirm(99)

    def test_reject(self):
        service.reject(1)
        self.assertIn(("reject", 1), self.fake.calls)


if __name__ == "__main__":
    unittest.main()
