"""Scan the inbox, classify each PDF, file it on the NAS and record it in MySQL."""

import re
import shutil
from pathlib import Path

from . import db
from .classify import UNCLASSIFIED, analyse
from .config import settings
from .extract import extract_text, file_sha256

REVIEW_FOLDER = "Needs Review"
DUPLICATES_FOLDER = "_duplicates"


def _safe(name: str) -> str:
    """Make a string safe to use as a single folder or file name."""
    return re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .") or "Unnamed"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def target_folder(type_row: dict, property_name, nas_root: Path) -> Path:
    if type_row["name"] == UNCLASSIFIED:
        return nas_root / REVIEW_FOLDER
    base = nas_root / _safe(type_row["nas_subfolder"] or type_row["name"])
    return base / _safe(property_name or "Unmatched")


def process_inbox(dry_run: bool = False, inbox: Path = None, nas_root: Path = None):
    inbox = inbox or settings.inbox_dir
    nas_root = nas_root or settings.nas_root
    results = []

    pdfs = sorted(
        p for p in inbox.rglob("*")
        if p.is_file() and p.suffix.lower() == ".pdf" and DUPLICATES_FOLDER not in p.parts
    )

    with db.connection() as conn:
        for pdf in pdfs:
            file_hash = file_sha256(pdf)

            if db.hash_exists(conn, file_hash):
                results.append((pdf.name, "duplicate", ""))
                if not dry_run:
                    dup_dir = inbox / DUPLICATES_FOLDER
                    dup_dir.mkdir(exist_ok=True)
                    shutil.move(str(pdf), str(_unique_path(dup_dir / pdf.name)))
                continue

            extraction = extract_text(pdf)
            analysis = analyse(extraction.text, pdf.name)
            type_row = db.get_type(conn, analysis.document_type)
            folder = target_folder(type_row, analysis.property_name, nas_root)
            destination = _unique_path(folder / _safe(pdf.name))

            expiry = analysis.expiry_date if type_row["has_expiry"] else None
            summary = (
                f"{analysis.document_type} (score {analysis.score:g}), "
                f"property={analysis.property_name or '-'}, expiry={expiry or '-'} "
                f"-> {destination}"
            )

            if dry_run:
                results.append((pdf.name, "would file", summary))
                continue

            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdf, destination)
            if file_sha256(destination) != file_hash:
                destination.unlink()
                raise IOError(f"Copy of {pdf.name} failed verification; original left in place")

            db.insert_document(
                conn,
                nas_path=str(destination),
                original_filename=pdf.name,
                file_hash=file_hash,
                page_count=extraction.page_count,
                extraction_method=extraction.method,
                document_type_id=type_row["id"],
                classification_score=analysis.score,
                property_id=analysis.property_id,
                company_code=analysis.company_code,
                counterparty=analysis.counterparty,
                document_date=analysis.document_date,
                extracted_text=extraction.text,
                expiry_date=expiry,
                expiry_confirmed=0,
                review_status="pending_review",
            )
            conn.commit()      # row is saved before the original is removed
            pdf.unlink()
            results.append((pdf.name, "filed", summary))

    return results
