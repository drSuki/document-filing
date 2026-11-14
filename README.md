# Document Filing Tool

Reads PDFs dropped into an inbox folder, works out what each one is, files it into the right folder on the NAS, records it in a MySQL database, and alerts you before documents expire.

## How it works

1. **Extract**: text is read directly from the PDF. Any page with no usable text is read by OCR (Tesseract).
2. **Classify**: each document type has weighted keyword phrases in `rules.json`. The highest score wins; if the score is low or too close to the runner-up, the document goes to `Needs Review`.
3. **Match**: the property, company and counterparty are matched from the text using `matching.json`.
4. **Expiry**: an expiry date is read from phrases such as "expiry date", "valid until" or "period of insurance".
5. **File**: the PDF is copied to `NAS_ROOT/<Type>/<Property>/`, verified by hash, recorded in the database, and only then removed from the inbox.
6. **Review**: every expiry date is stored as *unconfirmed*. Unconfirmed dates never raise alerts until you confirm them.
7. **Alert**: the alert date is the expiry date minus the lead time for that document type (contracts 3 months; certificates and insurance 1 month; invoices and statements have no expiry), or a per-document override.

## Setup

```
python -m venv venv
venv\Scripts\activate            (Windows)   or   source venv/bin/activate
pip install -r requirements.txt
```

Install Tesseract for OCR. On Windows, set `TESSERACT_CMD` in `.env`.

Create the database (this creates the `document_filing` database, its tables, and the alert view):

```
mysql -u root -p < schema.sql
```

Create a MySQL user for the tool with rights on `document_filing` only, then copy `.env.example` to `.env` and complete it.

Edit `matching.json` so it lists your real properties (ids matching your property table), companies and common counterparties.

## Daily use

```
python main.py process --dry-run    # show what would happen, change nothing
python main.py process              # classify, file and record everything in the inbox
python main.py review               # list documents awaiting review
python main.py confirm 14           # confirm document 14 as read
python main.py confirm 14 --expiry 2027-03-31    # confirm with a corrected expiry date
python main.py reject 15            # reject a wrong record
python main.py alerts               # show (or email) anything whose alert date has passed
```

Confirming a document also retires older documents of the same type, property, company and counterparty that expire earlier (they are marked superseded and stop alerting). This happens only on confirmation, so a misread date cannot retire a good record.

## Documents page in customer-contract (Contract Creator)

The Django app has a **Documents** button in its admin "Custom Actions" row. It opens a staff-only page to preview or run the inbox, see alerts that are due, and confirm (with a corrected expiry date) or reject documents awaiting review. It uses this project's `docfiling.service` module, so the filing logic stays in this repository.

On the server running customer-contract:

1. Put this project in a folder on that server and give it its own `.env`. Its dependencies (PyMuPDF, PyMySQL, pytesseract) are already listed in customer-contract's `requirements.in`, so install them into the Django environment.
2. Add `DOCFILING_HOME=C:\Projects\document-filing` (the folder holding `docfiling/`) to customer-contract's `.env`.
3. Run `python manage.py migrate`, which creates the permission `app.can_manage_documents`.
4. In the Django admin, grant **Can manage filed documents** to the users or group who should see the button. The user must also be staff.

The tool keeps its own database settings (`DB_*` in this project's `.env`), so the `document_filing` database stays separate from the Django and Sage databases.

## Scheduling

Run `process` and `alerts` from Windows Task Scheduler or cron, for example `process` every 15 minutes and `alerts` each weekday at 08:00.

## Changing lead times

Lead times are data. To change them:

```sql
UPDATE document_types SET alert_lead_months = 6 WHERE name = 'Contract';
```

For a single document: `UPDATE documents SET alert_override_months = 4 WHERE id = 14;`

## Tests

```
python -m unittest discover -s tests -v
```

## Known limits

- The database layer has not yet been run against a live MySQL server; please run `process --dry-run` first, then a single test PDF.
- Duplicate detection is by exact file hash, so a re-scan of the same paper document is not caught.
- If you correct a document's type or property at review, the file is not yet moved to the matching folder.
- A Django review screen (grouped by property) is the natural next step.
