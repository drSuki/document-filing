-- ---------------------------------------------------------------------------
-- Document filing tool: MySQL schema
-- Purpose : Record every PDF filed on the NAS, its classification, its expiry
--           date and the alert date derived from its document type.
--           All tool parameters (locations, thresholds, classification phrases,
--           property matching) live in this database, not in files.
-- Only the database connection details (and the SMTP password) stay in .env.
-- ---------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS document_filing
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE document_filing;

-- ---------------------------------------------------------------------------
-- 1. Settings: one row per scalar parameter
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    setting_key   VARCHAR(50)  NOT NULL,
    setting_value VARCHAR(500) NOT NULL DEFAULT '',
    description   VARCHAR(255) NULL,
    PRIMARY KEY (setting_key)
) ENGINE=InnoDB;

-- INSERT IGNORE: re-running this script never overwrites a value you have changed.
INSERT IGNORE INTO settings (setting_key, setting_value, description) VALUES
    ('nas_root',       '',  'Root folder on the NAS where filed documents are stored'),
    ('inbox_dir',      '',  'Folder where new PDFs are dropped for processing'),
    ('min_score',      '4', 'Minimum keyword score for a document type to be accepted'),
    ('min_margin',     '2', 'Minimum lead over the runner-up type, otherwise sent to review'),
    ('tesseract_cmd',  '',  'Full path to tesseract.exe if it is not on the PATH (optional)'),
    ('smtp_host',      '',  'SMTP server for alert emails; leave blank to print instead'),
    ('smtp_port',      '587', 'SMTP port'),
    ('smtp_user',      '',  'SMTP user name (the password stays in .env as SMTP_PASSWORD)'),
    ('alert_from',     '',  'From address for alert emails'),
    ('alert_to',       '',  'Recipient of alert emails');

-- ---------------------------------------------------------------------------
-- 2. Document types, with the alert lead time held as data, not code
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_types (
    id                INT UNSIGNED NOT NULL AUTO_INCREMENT,
    name              VARCHAR(50)  NOT NULL,
    has_expiry        TINYINT(1)   NOT NULL DEFAULT 1,
    alert_lead_months TINYINT UNSIGNED NULL,       -- NULL where has_expiry = 0
    nas_subfolder     VARCHAR(100) NULL,           -- default folder under the NAS root
    PRIMARY KEY (id),
    UNIQUE KEY uq_document_types_name (name)
) ENGINE=InnoDB;

INSERT INTO document_types (name, has_expiry, alert_lead_months, nas_subfolder) VALUES
    ('Contract',    1, 3,    'Contracts'),
    ('Certificate', 1, 1,    'Certificates'),
    ('Insurance',   1, 1,    'Insurance'),
    ('Invoice',     0, NULL, 'Invoices'),
    ('Statement',   0, NULL, 'Statements'),
    ('Unclassified',0, NULL, 'Needs Review')
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- ---------------------------------------------------------------------------
-- 3. Classification phrases: each phrase found in a document adds its weight
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS classification_phrases (
    id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
    document_type_id INT UNSIGNED NOT NULL,
    phrase           VARCHAR(100) NOT NULL,
    weight           DECIMAL(5,2) NOT NULL DEFAULT 1,
    active           TINYINT(1)   NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    UNIQUE KEY uq_class_phrase (document_type_id, phrase),
    CONSTRAINT fk_class_phrase_type
        FOREIGN KEY (document_type_id) REFERENCES document_types (id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 4. Date phrases: where to look for an expiry date, and for an issue date
--    pick = 'first' or 'last' date found after the phrase
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS expiry_phrases (
    id       INT UNSIGNED NOT NULL AUTO_INCREMENT,
    phrase   VARCHAR(100) NOT NULL,
    pick     ENUM('first','last') NOT NULL DEFAULT 'first',
    priority SMALLINT NOT NULL DEFAULT 100,        -- lower is tried first
    active   TINYINT(1) NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    UNIQUE KEY uq_expiry_phrase (phrase)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS issue_date_phrases (
    id       INT UNSIGNED NOT NULL AUTO_INCREMENT,
    phrase   VARCHAR(100) NOT NULL,
    priority SMALLINT NOT NULL DEFAULT 100,
    active   TINYINT(1) NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    UNIQUE KEY uq_issue_phrase (phrase)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 5. Matching: properties, companies and counterparties
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS properties (
    id     INT UNSIGNED NOT NULL AUTO_INCREMENT,
    name   VARCHAR(150) NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    UNIQUE KEY uq_properties_name (name)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS property_keywords (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
    property_id INT UNSIGNED NOT NULL,
    keyword     VARCHAR(150) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_property_keyword (property_id, keyword),
    CONSTRAINT fk_property_keyword
        FOREIGN KEY (property_id) REFERENCES properties (id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS company_keywords (
    id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_code VARCHAR(10)  NOT NULL,            -- e.g. JPP, TLD, REN
    keyword      VARCHAR(150) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_company_keyword (company_code, keyword)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS counterparties (
    id     INT UNSIGNED NOT NULL AUTO_INCREMENT,
    name   VARCHAR(150) NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    UNIQUE KEY uq_counterparties_name (name)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 6. Documents: one row per file held on the NAS.
--    relative_path is relative to the nas_root setting, so moving or remounting
--    the NAS means changing one setting, not every row.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    -- File identity
    relative_path         VARCHAR(500) NOT NULL,
    original_filename     VARCHAR(255) NOT NULL,
    file_hash             CHAR(64)     NOT NULL,   -- SHA-256, catches duplicates
    page_count            SMALLINT UNSIGNED NULL,
    extraction_method     ENUM('text','ocr') NOT NULL DEFAULT 'text',

    -- Classification
    document_type_id      INT UNSIGNED NOT NULL,
    classification_score  DECIMAL(5,2) NULL,       -- keyword score, for review
    property_id           INT UNSIGNED NULL,
    company_code          VARCHAR(10)  NULL,       -- e.g. JPP, TLD, REN
    counterparty          VARCHAR(200) NULL,       -- supplier, insurer, contractor

    -- Content
    document_date         DATE NULL,
    extracted_text        LONGTEXT NULL,

    -- Expiry and alerting
    expiry_date           DATE NULL,
    expiry_confirmed      TINYINT(1) NOT NULL DEFAULT 0,  -- 1 once you have checked it
    alert_override_months TINYINT UNSIGNED NULL,          -- per-document lead time

    -- Workflow
    review_status         ENUM('pending_review','confirmed','rejected')
                              NOT NULL DEFAULT 'pending_review',
    superseded_by_id      BIGINT UNSIGNED NULL,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                              ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uq_documents_hash (file_hash),
    KEY ix_documents_type (document_type_id),
    KEY ix_documents_property (property_id),
    KEY ix_documents_expiry (expiry_date),
    KEY ix_documents_status (review_status),
    FULLTEXT KEY ft_documents_text (extracted_text),

    CONSTRAINT fk_documents_type
        FOREIGN KEY (document_type_id) REFERENCES document_types (id),
    CONSTRAINT fk_documents_property
        FOREIGN KEY (property_id) REFERENCES properties (id) ON DELETE SET NULL,
    CONSTRAINT fk_documents_superseded
        FOREIGN KEY (superseded_by_id) REFERENCES documents (id)
        ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 7. Alert view: the alert date is calculated, so it never goes stale when a
--    lead time is changed. A per-document override takes precedence.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_document_alerts AS
SELECT
    d.id,
    d.relative_path,
    t.name                                   AS document_type,
    d.property_id,
    d.company_code,
    d.counterparty,
    d.expiry_date,
    d.expiry_confirmed,
    COALESCE(d.alert_override_months, t.alert_lead_months)
                                             AS lead_months,
    DATE_SUB(d.expiry_date,
             INTERVAL COALESCE(d.alert_override_months, t.alert_lead_months)
             MONTH)                          AS alert_date,
    CASE
        WHEN d.expiry_date < CURDATE() THEN 'Expired'
        WHEN DATE_SUB(d.expiry_date,
             INTERVAL COALESCE(d.alert_override_months, t.alert_lead_months)
             MONTH) <= CURDATE()             THEN 'Alert due'
        ELSE 'Not yet due'
    END                                      AS alert_status
FROM documents d
JOIN document_types t ON t.id = d.document_type_id
WHERE d.expiry_date IS NOT NULL
  AND d.superseded_by_id IS NULL
  AND d.review_status <> 'rejected'
  AND COALESCE(d.alert_override_months, t.alert_lead_months) IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Example: everything needing attention now, confirmed dates only
-- ---------------------------------------------------------------------------
-- SELECT * FROM v_document_alerts
-- WHERE alert_status IN ('Alert due','Expired')
--   AND expiry_confirmed = 1
-- ORDER BY expiry_date;
