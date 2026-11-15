> **Moved.** This tool is now a Django app inside the `customer-contract` repository
> (the `documents` folder), with its own `document_filing` database, admin screens and
> `manage.py` commands. This repository is kept for reference and is no longer developed.
> See `documents/README.md` in `customer-contract`.

# Document Filing Tool

Reads PDFs dropped into an inbox folder, works out what each one is, files it into the right folder on the NAS, records it in MySQL, and alerts you before documents expire.

**Everything is database-driven.** Only the database connection (and the SMTP password) live in `.env`. The NAS root, inbox, thresholds, classification phrases, date phrases, property matching and alert addresses are all rows in the `document_filing` database.

## How it works

1. **Extract**: text is read directly from the PDF. Any page with no usable text is read by OCR (Tesseract).
2. **Classify**: each document type has weighted phrases (table `classification_phrases`). The highest score wins; if the score is below `min_score` or too close to the runner-up (`min_margin`), the document goes to `Needs Review`.
3. **Match**: the property, company and counterparty are matched from the text (tables `properties`, `property_keywords`, `company_keywords`, `counterparties`).
4. **Expiry**: an expiry date is read using the phrases in `expiry_phrases` ("expiry date", "valid until", "period of insurance" and so on).
5. **File**: the PDF is copied to `<nas_root>/<Type>/<Property>/`, verified by hash, recorded in the database, and only then removed from the inbox. The database stores the path **relative to `nas_root`**, so moving or remounting the NAS means changing one setting.
6. **Review**: every expiry date is stored as *unconfirmed*. Unconfirmed dates never raise alerts until you confirm them.
7. **Alert**: the alert date is the expiry date minus the lead time for that document type (contracts 3 months; certificates and insurance 1 month; invoices and statements have no expiry), or a per-document override.

## Setup

```
python -m venv venv
venv\Scripts\activate            (Windows)   or   source venv/bin/activate
pip install -r requirements.txt
```

Install Tesseract for OCR. On Windows, if it is not on the PATH, set the `tesseract_cmd` setting (below).

**1. Create the database** (creates `document_filing`, its tables, default settings and the alert view):

```
mysql -u root -p < schema.sql
```

**2. Create a MySQL user** with rights on `document_filing` only:

```sql
CREATE USER 'docfiling'@'localhost' IDENTIFIED BY 'choose-a-password';
GRANT SELECT, INSERT, UPDATE, DELETE ON document_filing.* TO 'docfiling'@'localhost';
```

**3. Copy `.env.example` to `.env`** and enter the connection details.

**4. Load the starting rules:**

```
python main.py seed
```

This loads the phrases and the example properties from `seed/rules.json` and `seed/matching.json`. It is safe to repeat: rows already present are left alone and nothing is deleted. Edit `seed/matching.json` first if you want your real properties loaded in one go; the values in it now are examples.

**5. Set the locations:**

```
python main.py set nas_root /mnt/nas/Documents
python main.py set inbox_dir /mnt/nas/Inbox
python main.py settings              # show everything
```

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

## Changing the parameters

All of these are ordinary SQL tables, so they can be changed with any MySQL tool:

| What | Where |
| --- | --- |
| Locations, thresholds, SMTP host/user, alert addresses | table `settings` (or `main.py set`, or the Documents page) |
| Alert lead time per document type | `document_types.alert_lead_months` |
| Words that identify a document type | `classification_phrases` |
| Where to find an expiry or issue date | `expiry_phrases`, `issue_date_phrases` |
| Properties and the words that identify them | `properties`, `property_keywords` |
| Companies (JPP, TLD, REN) and counterparties | `company_keywords`, `counterparties` |

Examples:

```sql
UPDATE document_types SET alert_lead_months = 6 WHERE name = 'Contract';
UPDATE documents SET alert_override_months = 4 WHERE id = 14;      -- one document only
INSERT INTO classification_phrases (document_type_id, phrase, weight)
    SELECT id, 'fire alarm certificate', 5 FROM document_types WHERE name = 'Certificate';
```

Phrases are matched in lower case. Set `active = 0` on a row to switch it off without deleting it.

## Documents page in customer-contract (Contract Creator)

The Django app has a **Documents** button in its admin "Custom Actions" row. It opens a staff-only page to preview or run the inbox, see alerts that are due, confirm (with a corrected expiry date) or reject documents awaiting review, and edit the tool's settings. It uses this project's `docfiling.service` module, so the filing logic stays in this repository.

On the server running customer-contract:

1. Put this project in a folder on that server and give it its own `.env`. Its dependencies (PyMuPDF, PyMySQL, pytesseract) are already listed in customer-contract's `requirements.in`, so install them into the Django environment.
2. Add `DOCFILING_HOME=C:\Projects\document-filing` (the folder holding `docfiling/`) to customer-contract's `.env`.
3. Run `python manage.py migrate`, which creates the permission `app.can_manage_documents`.
4. In the Django admin, grant **Can manage filed documents** to the users or group who should see the button. The user must also be staff.

The tool keeps its own database connection (`DB_*` in this project's `.env`), so the `document_filing` database stays separate from the Django and Sage databases.

## Scheduling

Run `process` and `alerts` from Windows Task Scheduler or cron, for example `process` every 15 minutes and `alerts` each weekday at 08:00.

## Tests

```
python -m unittest discover -s tests -v
```

The end-to-end test in `tests/test_integration.py` runs against a real MySQL or MariaDB server and is skipped unless `DOCFILING_TEST_DB=1`. It only runs against a database named exactly `document_filing_test`, which it drops and recreates. See the file header for the command.

## Known limits

- Duplicate detection is by exact file hash, so a re-scan of the same paper document is not caught.
- If you correct a document's type or property at review, the file is not yet moved to the matching folder.
- The Documents page edits the scalar settings. The phrase and property tables are edited with SQL for now; a screen for them is a possible next step.
- Property names in the seed file are examples. The `properties` table here is the tool's own and is not linked to any property table elsewhere.
