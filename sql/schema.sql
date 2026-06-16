--------------------------------------------------------------------------------
-- Invoice OCR APEX Backend Schema
-- Local OCR + offline scoring + Oracle-backed correction learning
--------------------------------------------------------------------------------

CREATE TABLE inv_vendors (
    vendor_id           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vendor_code         VARCHAR2(50) UNIQUE,
    vendor_name         VARCHAR2(200) NOT NULL,
    tax_id              VARCHAR2(50),
    gstin               VARCHAR2(20),
    pan_number          VARCHAR2(15),
    address_line1       VARCHAR2(200),
    address_line2       VARCHAR2(200),
    city                VARCHAR2(100),
    state_province      VARCHAR2(100),
    postal_code         VARCHAR2(20),
    country             VARCHAR2(100) DEFAULT 'India',
    contact_name        VARCHAR2(200),
    contact_email       VARCHAR2(200),
    contact_phone       VARCHAR2(50),
    bank_name           VARCHAR2(200),
    bank_account_no     VARCHAR2(50),
    bank_ifsc_code      VARCHAR2(20),
    bank_branch         VARCHAR2(200),
    payment_terms_days  NUMBER(5) DEFAULT 30,
    default_currency    VARCHAR2(10) DEFAULT 'INR',
    is_active           VARCHAR2(1) DEFAULT 'Y' CHECK (is_active IN ('Y','N')),
    created_by          VARCHAR2(100),
    created_date        TIMESTAMP DEFAULT SYSTIMESTAMP,
    updated_by          VARCHAR2(100),
    updated_date        TIMESTAMP
);

CREATE TABLE inv_documents (
    document_id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_name           VARCHAR2(500) NOT NULL,
    mime_type           VARCHAR2(200),
    file_size           NUMBER,
    file_content        BLOB,
    upload_source       VARCHAR2(30) DEFAULT 'API'
                        CHECK (upload_source IN ('UPLOAD','CAMERA','EMAIL','API')),
    ocr_status          VARCHAR2(30) DEFAULT 'PENDING'
                        CHECK (ocr_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    ocr_raw_text        CLOB,
    ocr_structured_json CLOB,
    ocr_confidence      NUMBER(5,2),
    ocr_engine          VARCHAR2(50),
    ocr_processed_date  TIMESTAMP,
    invoice_id          NUMBER,
    page_count          NUMBER(5) DEFAULT 1,
    created_by          VARCHAR2(100),
    created_date        TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE TABLE inv_invoices (
    invoice_id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_number      VARCHAR2(100),
    vendor_id           NUMBER REFERENCES inv_vendors(vendor_id),
    vendor_name_raw     VARCHAR2(200),
    invoice_date        DATE,
    due_date            DATE,
    currency            VARCHAR2(10) DEFAULT 'INR',
    subtotal            NUMBER(15,2),
    cgst_amount         NUMBER(15,2) DEFAULT 0,
    sgst_amount         NUMBER(15,2) DEFAULT 0,
    igst_amount         NUMBER(15,2) DEFAULT 0,
    tax_amount          NUMBER(15,2) DEFAULT 0,
    discount_amount     NUMBER(15,2) DEFAULT 0,
    shipping_amount     NUMBER(15,2) DEFAULT 0,
    total_amount        NUMBER(15,2),
    amount_in_words     VARCHAR2(500),
    po_number           VARCHAR2(100),
    grn_number          VARCHAR2(100),
    vendor_gstin        VARCHAR2(20),
    buyer_gstin         VARCHAR2(20),
    place_of_supply     VARCHAR2(100),
    hsn_sac_code        VARCHAR2(20),
    irn_number          VARCHAR2(100),
    eway_bill_no        VARCHAR2(50),
    bank_account_no     VARCHAR2(50),
    bank_ifsc           VARCHAR2(20),
    bank_name           VARCHAR2(200),
    payment_terms       VARCHAR2(200),
    description         VARCHAR2(4000),
    notes               VARCHAR2(4000),
    status              VARCHAR2(30) DEFAULT 'DRAFT'
                        CHECK (status IN (
                            'DRAFT','EXTRACTING','EXTRACTED','REVIEW',
                            'INCOMPLETE','PENDING_APPROVAL','APPROVED',
                            'REJECTED','PAYMENT_INITIATED','PAID','CANCELLED'
                        )),
    extraction_confidence NUMBER(5,2),
    is_complete         VARCHAR2(1) DEFAULT 'N' CHECK (is_complete IN ('Y','N')),
    missing_field_count NUMBER(5) DEFAULT 0,
    created_by          VARCHAR2(100),
    created_date        TIMESTAMP DEFAULT SYSTIMESTAMP,
    updated_by          VARCHAR2(100),
    updated_date        TIMESTAMP
);

ALTER TABLE inv_documents ADD CONSTRAINT fk_doc_invoice
    FOREIGN KEY (invoice_id) REFERENCES inv_invoices(invoice_id);

CREATE TABLE inv_line_items (
    line_item_id        NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id          NUMBER NOT NULL REFERENCES inv_invoices(invoice_id),
    line_number         NUMBER(5),
    item_description    VARCHAR2(1000),
    item_code           VARCHAR2(100),
    hsn_sac_code        VARCHAR2(20),
    quantity            NUMBER(15,3),
    unit                VARCHAR2(30),
    unit_price          NUMBER(15,4),
    discount_pct        NUMBER(5,2) DEFAULT 0,
    discount_amount     NUMBER(15,2) DEFAULT 0,
    tax_rate            NUMBER(5,2),
    tax_amount          NUMBER(15,2),
    cgst_rate           NUMBER(5,2),
    cgst_amount         NUMBER(15,2),
    sgst_rate           NUMBER(5,2),
    sgst_amount         NUMBER(15,2),
    igst_rate           NUMBER(5,2),
    igst_amount         NUMBER(15,2),
    line_total          NUMBER(15,2),
    created_date        TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE TABLE inv_field_synonyms (
    synonym_id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    db_column_name      VARCHAR2(100) NOT NULL,
    db_table_name       VARCHAR2(100) DEFAULT 'INV_INVOICES',
    synonym_text        VARCHAR2(200) NOT NULL,
    synonym_pattern     VARCHAR2(500),
    confidence_boost    NUMBER(3,2) DEFAULT 0,
    is_active           VARCHAR2(1) DEFAULT 'Y' CHECK (is_active IN ('Y','N')),
    created_date        TIMESTAMP DEFAULT SYSTIMESTAMP,
    CONSTRAINT uq_inv_synonym UNIQUE (db_column_name, synonym_text)
);

CREATE TABLE inv_extraction_results (
    extraction_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id         NUMBER NOT NULL REFERENCES inv_documents(document_id),
    invoice_id          NUMBER REFERENCES inv_invoices(invoice_id),
    field_label         VARCHAR2(200),
    field_value         VARCHAR2(4000),
    mapped_column       VARCHAR2(100),
    confidence_score    NUMBER(5,2),
    bounding_box        VARCHAR2(200),
    page_number         NUMBER(3) DEFAULT 1,
    is_verified         VARCHAR2(1) DEFAULT 'N' CHECK (is_verified IN ('Y','N')),
    verified_by         VARCHAR2(100),
    verified_date       TIMESTAMP,
    ai_reasoning        VARCHAR2(4000),
    created_date        TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE TABLE inv_dynamic_fields (
    field_id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    field_name          VARCHAR2(100) NOT NULL UNIQUE,
    display_name        VARCHAR2(200),
    data_type           VARCHAR2(30) DEFAULT 'TEXT',
    is_known_business   VARCHAR2(1) DEFAULT 'N' CHECK (is_known_business IN ('Y','N')),
    created_date        TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE TABLE inv_invoice_field_values (
    value_id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id          NUMBER NOT NULL REFERENCES inv_invoices(invoice_id),
    field_id            NUMBER NOT NULL REFERENCES inv_dynamic_fields(field_id),
    raw_label           VARCHAR2(200),
    field_value         VARCHAR2(4000),
    confidence_score    NUMBER(5,2),
    source_type         VARCHAR2(30) DEFAULT 'OCR',
    is_verified         VARCHAR2(1) DEFAULT 'N' CHECK (is_verified IN ('Y','N')),
    verified_by         VARCHAR2(100),
    verified_date       TIMESTAMP,
    created_date        TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE TABLE inv_validation_rules (
    rule_id             NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rule_name           VARCHAR2(100) NOT NULL,
    target_column       VARCHAR2(100) NOT NULL,
    target_table        VARCHAR2(100) DEFAULT 'INV_INVOICES',
    rule_type           VARCHAR2(30) NOT NULL
                        CHECK (rule_type IN ('MANDATORY','FORMAT','RANGE','CROSS_FIELD','CUSTOM')),
    rule_expression     VARCHAR2(4000),
    error_message       VARCHAR2(500),
    severity            VARCHAR2(20) DEFAULT 'ERROR'
                        CHECK (severity IN ('ERROR','WARNING','INFO')),
    is_blocking         VARCHAR2(1) DEFAULT 'Y' CHECK (is_blocking IN ('Y','N')),
    is_active           VARCHAR2(1) DEFAULT 'Y' CHECK (is_active IN ('Y','N')),
    display_order       NUMBER(5) DEFAULT 100,
    created_date        TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE TABLE inv_missing_fields (
    missing_id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id          NUMBER NOT NULL REFERENCES inv_invoices(invoice_id),
    field_name          VARCHAR2(100) NOT NULL,
    field_label         VARCHAR2(200),
    rule_id             NUMBER REFERENCES inv_validation_rules(rule_id),
    issue_type          VARCHAR2(30) DEFAULT 'MISSING'
                        CHECK (issue_type IN ('MISSING','INVALID','WARNING')),
    message             VARCHAR2(500),
    is_resolved         VARCHAR2(1) DEFAULT 'N' CHECK (is_resolved IN ('Y','N')),
    resolved_by         VARCHAR2(100),
    resolved_date       TIMESTAMP,
    created_date        TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE TABLE inv_ai_learning_log (
    log_id              NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id         NUMBER,
    invoice_id          NUMBER,
    vendor_id           NUMBER,
    field_label_raw     VARCHAR2(200),
    mapped_to_column    VARCHAR2(100),
    was_correct         VARCHAR2(1),
    corrected_to_column VARCHAR2(100),
    ai_model            VARCHAR2(100),
    prompt_used         CLOB,
    response_received   CLOB,
    processing_time_ms  NUMBER,
    created_date        TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE INDEX idx_vendor_name ON inv_vendors(UPPER(vendor_name));
CREATE INDEX idx_vendor_gstin ON inv_vendors(gstin);
CREATE INDEX idx_doc_invoice ON inv_documents(invoice_id);
CREATE INDEX idx_doc_ocr_status ON inv_documents(ocr_status);
CREATE INDEX idx_inv_status ON inv_invoices(status);
CREATE INDEX idx_inv_vendor ON inv_invoices(vendor_id);
CREATE INDEX idx_inv_number ON inv_invoices(invoice_number);
CREATE INDEX idx_inv_date ON inv_invoices(invoice_date);
CREATE INDEX idx_li_invoice ON inv_line_items(invoice_id);
CREATE INDEX idx_syn_column ON inv_field_synonyms(db_column_name);
CREATE INDEX idx_syn_text ON inv_field_synonyms(UPPER(synonym_text));
CREATE INDEX idx_ext_doc ON inv_extraction_results(document_id);
CREATE INDEX idx_ext_inv ON inv_extraction_results(invoice_id);
CREATE INDEX idx_mf_invoice ON inv_missing_fields(invoice_id);
CREATE INDEX idx_mf_resolved ON inv_missing_fields(is_resolved);
CREATE INDEX idx_dyn_field ON inv_invoice_field_values(invoice_id, field_id);
CREATE INDEX idx_ai_vendor ON inv_ai_learning_log(vendor_id);

CREATE OR REPLACE TRIGGER trg_inv_invoices_upd
BEFORE UPDATE ON inv_invoices
FOR EACH ROW
BEGIN
    :NEW.updated_date := SYSTIMESTAMP;
END;
/

CREATE OR REPLACE TRIGGER trg_inv_vendors_upd
BEFORE UPDATE ON inv_vendors
FOR EACH ROW
BEGIN
    :NEW.updated_date := SYSTIMESTAMP;
END;
/

INSERT INTO inv_validation_rules (rule_name, target_column, rule_type, rule_expression, error_message, severity, is_blocking, display_order)
VALUES ('Invoice Number Required', 'INVOICE_NUMBER', 'MANDATORY', 'IS NOT NULL', 'Invoice number is required', 'ERROR', 'Y', 10);

INSERT INTO inv_validation_rules (rule_name, target_column, rule_type, rule_expression, error_message, severity, is_blocking, display_order)
VALUES ('Vendor Name Required', 'VENDOR_NAME_RAW', 'MANDATORY', 'IS NOT NULL', 'Vendor/supplier name is required', 'ERROR', 'Y', 20);

INSERT INTO inv_validation_rules (rule_name, target_column, rule_type, rule_expression, error_message, severity, is_blocking, display_order)
VALUES ('Invoice Date Required', 'INVOICE_DATE', 'MANDATORY', 'IS NOT NULL', 'Invoice date is required', 'ERROR', 'Y', 30);

INSERT INTO inv_validation_rules (rule_name, target_column, rule_type, rule_expression, error_message, severity, is_blocking, display_order)
VALUES ('Total Amount Required', 'TOTAL_AMOUNT', 'MANDATORY', 'IS NOT NULL', 'Total amount is required', 'ERROR', 'Y', 40);

INSERT INTO inv_validation_rules (rule_name, target_column, rule_type, rule_expression, error_message, severity, is_blocking, display_order)
VALUES ('Total Amount Positive', 'TOTAL_AMOUNT', 'RANGE', '> 0', 'Total amount must be greater than zero', 'ERROR', 'Y', 50);

INSERT INTO inv_validation_rules (rule_name, target_column, rule_type, rule_expression, error_message, severity, is_blocking, display_order)
VALUES ('Vendor GSTIN Format', 'VENDOR_GSTIN', 'FORMAT', 'GSTIN', 'Invalid GSTIN format', 'WARNING', 'N', 70);

INSERT INTO inv_field_synonyms (db_column_name, synonym_text, confidence_boost) VALUES ('INVOICE_NUMBER', 'Invoice No', 0.10);
INSERT INTO inv_field_synonyms (db_column_name, synonym_text, confidence_boost) VALUES ('INVOICE_NUMBER', 'Bill No', 0.10);
INSERT INTO inv_field_synonyms (db_column_name, synonym_text, confidence_boost) VALUES ('VENDOR_NAME_RAW', 'Supplier Name', 0.10);
INSERT INTO inv_field_synonyms (db_column_name, synonym_text, confidence_boost) VALUES ('VENDOR_NAME_RAW', 'Vendor Name', 0.10);
INSERT INTO inv_field_synonyms (db_column_name, synonym_text, confidence_boost) VALUES ('INVOICE_DATE', 'Invoice Date', 0.10);
INSERT INTO inv_field_synonyms (db_column_name, synonym_text, confidence_boost) VALUES ('TOTAL_AMOUNT', 'Grand Total', 0.10);
INSERT INTO inv_field_synonyms (db_column_name, synonym_text, confidence_boost) VALUES ('SUBTOTAL', 'Taxable Value', 0.10);
INSERT INTO inv_field_synonyms (db_column_name, synonym_text, confidence_boost) VALUES ('VENDOR_GSTIN', 'GSTIN', 0.10);

COMMIT;
