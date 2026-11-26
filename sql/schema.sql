-- MigrateRight target schema, shaped like SAP S/4HANA tables (simplified).
-- Portable SQL: runs on PostgreSQL and SQLite. Re-created on every pipeline run.
-- Column names are lower case so PostgreSQL and SQLite behave the same.

-- ===== Business Partner =====================================================
DROP TABLE IF EXISTS tgt_but000;
CREATE TABLE tgt_but000 (            -- BP general data
    partner     VARCHAR(10) PRIMARY KEY,
    bu_type     VARCHAR(1)  NOT NULL, -- 1 person, 2 organisation
    bu_group    VARCHAR(4),           -- BP grouping (number range / account group)
    name_org1   VARCHAR(40) NOT NULL,
    name_org2   VARCHAR(40),
    bpext       VARCHAR(20),          -- external / legacy number
    crdat       VARCHAR(10)
);

DROP TABLE IF EXISTS tgt_but020;
CREATE TABLE tgt_but020 (            -- BP -> address link
    partner     VARCHAR(10) NOT NULL,
    addrnumber  VARCHAR(10) NOT NULL,
    PRIMARY KEY (partner, addrnumber)
);

DROP TABLE IF EXISTS tgt_adrc;
CREATE TABLE tgt_adrc (              -- central address (phone/e-mail simplified from ADR2/ADR6)
    addrnumber  VARCHAR(10) PRIMARY KEY,
    name1       VARCHAR(40),
    street      VARCHAR(60),
    city1       VARCHAR(40),
    post_code1  VARCHAR(10),
    country     VARCHAR(3),
    tel_number  VARCHAR(30),
    smtp_addr   VARCHAR(241)
);

DROP TABLE IF EXISTS tgt_but100;
CREATE TABLE tgt_but100 (            -- BP roles
    partner     VARCHAR(10) NOT NULL,
    rltyp       VARCHAR(6)  NOT NULL, -- FLCU01 customer, FLVN01 vendor
    PRIMARY KEY (partner, rltyp)
);

DROP TABLE IF EXISTS tgt_cvi_cust_link;
CREATE TABLE tgt_cvi_cust_link (     -- legacy customer number -> BP
    partner     VARCHAR(10) NOT NULL,
    kunnr       VARCHAR(10) PRIMARY KEY
);

DROP TABLE IF EXISTS tgt_cvi_vend_link;
CREATE TABLE tgt_cvi_vend_link (     -- legacy vendor number -> BP
    partner     VARCHAR(10) NOT NULL,
    lifnr       VARCHAR(10) PRIMARY KEY
);

-- ===== Product master =======================================================
DROP TABLE IF EXISTS tgt_mara;
CREATE TABLE tgt_mara (              -- general material data
    matnr       VARCHAR(40) PRIMARY KEY,
    mtart       VARCHAR(4)  NOT NULL,
    meins       VARCHAR(3)  NOT NULL,
    bismt       VARCHAR(40),          -- old (legacy) material number
    ersda       VARCHAR(10)
);

DROP TABLE IF EXISTS tgt_makt;
CREATE TABLE tgt_makt (              -- material descriptions
    matnr       VARCHAR(40) NOT NULL,
    spras       VARCHAR(1)  NOT NULL,
    maktx       VARCHAR(40) NOT NULL,
    PRIMARY KEY (matnr, spras)
);

DROP TABLE IF EXISTS tgt_mbew;
CREATE TABLE tgt_mbew (              -- material valuation
    matnr       VARCHAR(40) NOT NULL,
    bwkey       VARCHAR(4)  NOT NULL,
    stprs       NUMERIC(13, 2),
    peinh       INTEGER,
    PRIMARY KEY (matnr, bwkey)
);

-- ===== Migration control tables =============================================
DROP TABLE IF EXISTS mig_quarantine;
CREATE TABLE mig_quarantine (        -- every failed rule, one row per failure
    object      VARCHAR(10) NOT NULL,
    legacy_id   VARCHAR(40) NOT NULL,
    rule        VARCHAR(30) NOT NULL,
    field       VARCHAR(30),
    value       VARCHAR(255)
);

DROP TABLE IF EXISTS mig_merge_log;
CREATE TABLE mig_merge_log (         -- duplicates merged into a survivor
    object       VARCHAR(10) NOT NULL,
    survivor_id  VARCHAR(40) NOT NULL,
    merged_id    VARCHAR(40) NOT NULL,
    score        NUMERIC(5, 1),
    match_reason VARCHAR(120)
);

DROP TABLE IF EXISTS mig_shared_bp;
CREATE TABLE mig_shared_bp (         -- vendors that re-used a customer's BP (CVI)
    partner     VARCHAR(10) NOT NULL,
    vendor_id   VARCHAR(10) NOT NULL
);
