"""Command line for the document filing tool.

    python main.py process [--dry-run]
    python main.py review
    python main.py confirm ID [--expiry YYYY-MM-DD]
    python main.py reject ID
    python main.py alerts [--no-email]
"""

import argparse
import sys
from datetime import datetime

from docfiling import alerts, db, filer


def cmd_process(args):
    results = filer.process_inbox(dry_run=args.dry_run)
    if not results:
        print("Inbox is empty.")
    for name, status, detail in results:
        print(f"{status.upper():<10} {name}\n           {detail}" if detail else f"{status.upper():<10} {name}")


def cmd_review(args):
    with db.connection() as conn:
        rows = db.list_pending(conn)
    if not rows:
        print("Nothing awaiting review.")
        return
    for r in rows:
        print(
            f"#{r['id']:<5} {r['document_type']:<12} score {r['classification_score']}  "
            f"expiry {r['expiry_date'] or '-'}  property {r['property_id'] or '-'}  "
            f"{r['counterparty'] or '-'}\n       {r['nas_path']}"
        )


def cmd_confirm(args):
    expiry = datetime.strptime(args.expiry, "%Y-%m-%d").date() if args.expiry else None
    with db.connection() as conn:
        db.confirm_document(conn, args.id, expiry)
        doc = db.get_document(conn, args.id)
        if doc is None:
            sys.exit(f"No document with id {args.id}")
        retired = db.supersede_older(conn, doc)
    print(f"Document #{args.id} confirmed. Superseded {retired} older document(s).")


def cmd_reject(args):
    with db.connection() as conn:
        db.reject_document(conn, args.id)
    print(f"Document #{args.id} rejected.")


def cmd_alerts(args):
    print(alerts.run_alerts(send=not args.no_email))


def main():
    parser = argparse.ArgumentParser(description="Document filing tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("process", help="Classify and file PDFs from the inbox")
    p.add_argument("--dry-run", action="store_true", help="Show what would happen; change nothing")
    p.set_defaults(func=cmd_process)

    sub.add_parser("review", help="List documents awaiting review").set_defaults(func=cmd_review)

    p = sub.add_parser("confirm", help="Confirm a document, optionally correcting its expiry date")
    p.add_argument("id", type=int)
    p.add_argument("--expiry", help="Corrected expiry date, YYYY-MM-DD")
    p.set_defaults(func=cmd_confirm)

    p = sub.add_parser("reject", help="Reject a document record")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser("alerts", help="Show or email documents whose alert date has passed")
    p.add_argument("--no-email", action="store_true")
    p.set_defaults(func=cmd_alerts)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
