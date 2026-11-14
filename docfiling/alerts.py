"""Expiry alert summary: printed, or emailed when SMTP is configured."""

import smtplib
from email.message import EmailMessage
from pathlib import Path

from . import db, params as params_module

NOTHING_DUE = "No document alerts are due."


def build_summary(rows, unconfirmed: int) -> str:
    if not rows and not unconfirmed:
        return NOTHING_DUE
    lines = []
    if rows:
        lines.append("Documents requiring attention:\n")
        for row in rows:
            lines.append(
                f"  [{row['alert_status']}] {row['document_type']} - "
                f"{row['counterparty'] or 'no counterparty'} - "
                f"property {row.get('property_name') or row['property_id'] or '?'} - "
                f"expires {row['expiry_date']} (alert lead {row['lead_months']} months)\n"
                f"    {row['nas_path']}"
            )
    if unconfirmed:
        lines.append(
            f"\n{unconfirmed} document(s) have an unconfirmed expiry date and "
            "will not alert until reviewed."
        )
    return "\n".join(lines)


def run_alerts(send: bool = True) -> str:
    with db.connection() as conn:
        params = params_module.build_params(conn)
        rows = db.due_alerts(conn)
        names = db.property_names(conn)
        unconfirmed = db.unconfirmed_expiry_count(conn)

    for row in rows:
        row["property_name"] = names.get(row["property_id"])
        row["nas_path"] = str(Path(params.nas_root) / row["relative_path"])
    body = build_summary(rows, unconfirmed)

    if send and params.smtp_host and params.alert_to and body != NOTHING_DUE:
        message = EmailMessage()
        message["Subject"] = f"Document expiry alerts ({len(rows)} due)"
        message["From"] = params.alert_from or params.smtp_user
        message["To"] = params.alert_to
        message.set_content(body)
        with smtplib.SMTP(params.smtp_host, params.smtp_port) as server:
            server.starttls()
            if params.smtp_user:
                server.login(params.smtp_user, params.smtp_password)
            server.send_message(message)
    return body
