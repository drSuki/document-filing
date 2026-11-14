"""Expiry alert summary: printed, or emailed when SMTP is configured."""

import smtplib
from email.message import EmailMessage

from . import db
from .config import settings


def build_summary(rows, unconfirmed: int) -> str:
    if not rows and not unconfirmed:
        return "No document alerts are due."
    lines = []
    if rows:
        lines.append("Documents requiring attention:\n")
        for row in rows:
            lines.append(
                f"  [{row['alert_status']}] {row['document_type']} - "
                f"{row['counterparty'] or 'no counterparty'} - "
                f"property {row['property_id'] or '?'} - expires {row['expiry_date']} "
                f"(alert lead {row['lead_months']} months)\n    {row['nas_path']}"
            )
    if unconfirmed:
        lines.append(
            f"\n{unconfirmed} document(s) have an unconfirmed expiry date and "
            "will not alert until reviewed."
        )
    return "\n".join(lines)


def run_alerts(send: bool = True) -> str:
    with db.connection() as conn:
        rows = db.due_alerts(conn)
        unconfirmed = db.unconfirmed_expiry_count(conn)
    body = build_summary(rows, unconfirmed)

    if send and settings.smtp_host and settings.alert_to and body != "No document alerts are due.":
        message = EmailMessage()
        message["Subject"] = f"Document expiry alerts ({len(rows)} due)"
        message["From"] = settings.alert_from or settings.smtp_user
        message["To"] = settings.alert_to
        message.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    return body
