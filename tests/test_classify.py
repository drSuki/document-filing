"""Tests for extraction and classification. No database is required."""

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf

from docfiling.classify import UNCLASSIFIED, analyse, parse_date
from docfiling.extract import extract_text, file_sha256

SAMPLES = {
    "Insurance": (
        "Certificate of Insurance\nPolicy Number: AV-1234567\nInsurer: Aviva\n"
        "Landlord insurance for 1 Example Street\n"
        "Period of insurance: 01/03/2026 to 28/02/2027\nSum insured: 250,000"
    ),
    "Certificate": (
        "Landlord Gas Safety Record\nProperty: Sample Cottage, 2 Sample Lane\n"
        "Date of inspection: 12 September 2026\n"
        "Next inspection due: 11 September 2027\nCertificate number 889221"
    ),
    "Contract": (
        "ASSURED SHORTHOLD TENANCY AGREEMENT\nThis agreement is made between "
        "Jarvs Property Partnership (the Landlord) and the Tenant for "
        "1 Example Street.\nEnd date: 30 June 2027\nSigned by the parties."
    ),
    "Invoice": (
        "INVOICE\nInvoice number 4471\nInvoice date: 02/11/2026\n"
        "Amount due: 480.00\nVAT registration 123 4567 89"
    ),
    "Statement": (
        "Statement of account\nStatement date: 31/10/2026\n"
        "Opening balance 1,200.00\nClosing balance 640.00"
    ),
}


def make_pdf(path: Path, text: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    doc.save(path)
    doc.close()


class TestDates(unittest.TestCase):
    def test_numeric(self):
        self.assertEqual(parse_date("01/03/2026"), date(2026, 3, 1))

    def test_worded(self):
        self.assertEqual(parse_date("12 September 2026"), date(2026, 9, 12))
        self.assertEqual(parse_date("3rd Mar 2027"), date(2027, 3, 3))

    def test_invalid(self):
        self.assertIsNone(parse_date("31/02/2026"))


class TestAnalysis(unittest.TestCase):
    def test_each_type(self):
        for expected, text in SAMPLES.items():
            with self.subTest(expected):
                self.assertEqual(analyse(text).document_type, expected)

    def test_insurance_expiry_takes_end_of_period(self):
        self.assertEqual(analyse(SAMPLES["Insurance"]).expiry_date, date(2027, 2, 28))

    def test_certificate_expiry_and_property(self):
        result = analyse(SAMPLES["Certificate"])
        self.assertEqual(result.expiry_date, date(2027, 9, 11))
        self.assertEqual(result.document_date, date(2026, 9, 12))
        self.assertEqual(result.property_id, 2)

    def test_contract_company_and_property(self):
        result = analyse(SAMPLES["Contract"])
        self.assertEqual(result.expiry_date, date(2027, 6, 30))
        self.assertEqual(result.company_code, "JPP")
        self.assertEqual(result.property_id, 1)

    def test_unrecognised_goes_to_review(self):
        self.assertEqual(analyse("Dear Sir, thank you for your letter.").document_type, UNCLASSIFIED)


class TestExtraction(unittest.TestCase):
    def test_text_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "gas.pdf"
            make_pdf(pdf, SAMPLES["Certificate"])
            result = extract_text(pdf)
            self.assertEqual(result.method, "text")
            self.assertEqual(result.page_count, 1)
            self.assertEqual(analyse(result.text, pdf.name).document_type, "Certificate")

    def test_scanned_pdf_uses_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdf"
            make_pdf(source, SAMPLES["Invoice"])
            with pymupdf.open(source) as src:
                png = src[0].get_pixmap(dpi=200).tobytes("png")
            scan = Path(tmp) / "scan.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_image(page.rect, stream=png)
            doc.save(scan)
            doc.close()
            result = extract_text(scan)
            self.assertEqual(result.method, "ocr")
            self.assertEqual(analyse(result.text, scan.name).document_type, "Invoice")

    def test_hash_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "a.pdf"
            make_pdf(pdf, "hello")
            self.assertEqual(file_sha256(pdf), file_sha256(pdf))


if __name__ == "__main__":
    unittest.main()
