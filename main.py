"""Command line for the document filing tool.

    python main.py seed [--rules] [--matching]
    python main.py settings
    python main.py set KEY VALUE
    python main.py process [--dry-run]
    python main.py review
    python main.py confirm ID [--expiry YYYY-MM-DD]
    python main.py reject ID
    python main.py alerts [--no-email]
"""

import argparse
import sys
from datetime import datetime

from docfiling import alerts, db, service
from docfiling.params import SettingsError


def cmd_seed(args):
    both = not (args.rules or args.matching)
    counts = service.seed(rules=args.rules or both, matching=args.matching or both)
    for name, added in counts.items():
        print(f"{name:<24} {added} added")
    print("Rows already present were left unchanged.")


def cmd_settings(args):
    for row in service.editable_settings():
        print(f"{row['setting_key']:<15} = {row['setting_value'] or '(empty)'}\n{'':<15}   {row['description']}")


def cmd_set(args):
    changed = service.save_settings({args.key: args.value})
    print(f"{args.key} updated." if changed else f"{args.key} was already set to that value.")


def cmd_process(args):
    results = service.process_inbox(dry_run=args.dry_run)
    if not results:
        print("Inbox is empty.")
    for name, status, detail in results:
        print(f"{status.upper():<10} {name}\n           {detail}" if detail else f"{status.upper():<10} {name}")


def cmd_review(args):
    rows = service.pending_documents()
    if not rows:
        print("Nothing awaiting review.")
        return
    for r in rows:
        print(
            f"#{r['id']:<5} {r['document_type']:<12} score {r['classification_score']}  "
            f"expiry {r['expiry_date'] or '-'}  property {r['property_name'] or '-'}  "
            f"{r['counterparty'] or '-'}\n       {r['nas_path']}"
        )


def cmd_confirm(args):
    expiry = datetime.strptime(args.expiry, "%Y-%m-%d").date() if args.expiry else None
    try:
        retired = service.confirm(args.id, expiry)
    except LookupError as error:
        sys.exit(str(error))
    print(f"Document #{args.id} confirmed. Superseded {retired} older document(s).")


def cmd_reject(args):
    try:
        service.reject(args.id)
    except LookupError as error:
        sys.exit(str(error))
    print(f"Document #{args.id} rejected.")


def cmd_alerts(args):
    print(alerts.run_alerts(send=not args.no_email))


def main():
    parser = argparse.ArgumentParser(description="Document filing tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("seed", help="Load the starting rules and matching from seed/*.json")
    p.add_argument("--rules", action="store_true", help="Load classification and date phrases only")
    p.add_argument("--matching", action="store_true", help="Load properties, companies and counterparties only")
    p.set_defaults(func=cmd_seed)

    sub.add_parser("settings", help="Show the current settings").set_defaults(func=cmd_settings)

    p = sub.add_parser("set", help="Change a setting, for example: set nas_root /mnt/nas/Documents")
    p.add_argument("key")
    p.add_argument("value")
    p.set_defaults(func=cmd_set)

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
    try:
        args.func(args)
    except SettingsError as error:
        sys.exit(f"Settings problem: {error}")


if __name__ == "__main__":
    main()
