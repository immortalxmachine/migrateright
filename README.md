# MigrateRight

**Case study: migrating a Brazilian retailer's customer and vendor master and a UK retailer's product master from
legacy ECC-style extracts to S/4HANA Business Partner and product master.**

Profiling, rule-based cleansing, address standardisation, de-duplication with survivorship, loading into
S/4HANA-shaped tables, and reconciliation reports (Excel + Streamlit) that a business user can sign off –
all on **real public data** (Olist Brazilian E-Commerce and Online Retail II).

![Streamlit sign-off flow](docs/screenshots/demo.gif)

[![CI](https://github.com/immortalxmachine/migrateright/actions/workflows/ci.yml/badge.svg)](https://github.com/immortalxmachine/migrateright/actions/workflows/ci.yml)

> **Case-study notice.** The data is real but public and anonymised. "Legacy ECC extracts" are shaped from the
> public files (KNA1/LFA1/MARA-like field names); no real SAP system or company is involved. Target fields the
> sources do not contain are **left empty, never invented** (see [Mapping gaps](#mapping-gaps)).

## Results of the latest run (generated from `metrics.json`)

<!-- METRICS:START -->
| Object | Records in | Loaded | Quarantined | % rejected | Duplicates merged | Recon checks |
|---|---:|---:|---:|---:|---:|---:|
| Customers (Olist customers → BP, role FLCU01) | 9,931 | 9,524 | 74 | 0.75 % | 333 | 20/20 |
| Vendors (Olist sellers → BP, role FLVN01) | 3,095 | 2,716 | 379 | 12.25 % | 0 | 20/20 |
| Materials (Online Retail II → MARA/MAKT/MBEW) | 5,304 | 3,927 | 1,266 | 23.87 % | 111 | 12/12 |
| **Total** | **18,330** | **16,167** | **1,719** | **9.38 %** | **444** | **52/52 PASS** |

- **12,240 Business Partners** created (9,524 customers,
  2,716 vendors) and 3,927 products.
- **Rejected % of records in, by reason** (a record can fail several rules):
  customers: OBSOLETE 0.39 %, ZIP_NOT_FOUND 0.35 % · vendors: OBSOLETE 9.79 %, CITY_ZIP_MISMATCH 1.36 %, ZIP_STATE_MISMATCH 1.13 %, ZIP_NOT_FOUND 0.23 % · materials: OBSOLETE 23.27 %, MISSING_PRICE 7.05 %, MISSING_MANDATORY 6.69 %, NON_PRODUCT 0.51 %, INVALID_DESCRIPTION 0.26 %.
- **City standardisation** against Olist geolocation: customers 99.65 % exact;
  vendors 96.9 % exact, **47 corrected** by fuzzy match or by stripping
  extra text (`sao pauo`, `mogi das cruzes / sp`), 49 unmatched
  (`sp`, `bahia`, an e-mail address typed as the city…).
- **Real duplicates:** 9,931 customer rows belong to 9,593 real customers
  (`customer_unique_id`) → 333 merged (the rest of the 338
  duplicate rows were already quarantined). Materials: 111 codes that differ only
  in case (`85123A`/`85123a`).
- **Location-only duplicate matcher vs. the real id** (same zip prefix + fuzzy city ≥ 90 + same state):
  precision **3.83 %**, recall **90.58 %** (327 of
  361 true pairs found, 8,530 pairs proposed). Without a name, e-mail or
  CPF the address alone cannot tell people apart, so merging is done on `customer_unique_id` only.
<!-- METRICS:END -->

## Pipeline

```mermaid
flowchart LR
    A[Extract<br/>Olist customers / sellers<br/>Online Retail II stock codes] --> B[Profile<br/>completeness, uniqueness,<br/>validity, shapes]
    B --> C[Cleanse<br/>zip, state, city vs<br/>geolocation reference]
    C --> V[Validate<br/>rules.yaml<br/>failures -> quarantine]
    V --> D[De-duplicate<br/>customer_unique_id / MATNR<br/>survivorship -> merge log]
    D --> E[Map<br/>mapping.yaml<br/>BP: BUT000/BUT020/ADRC/BUT100<br/>Product: MARA/MAKT/MBEW]
    E --> F[Load<br/>PostgreSQL or SQLite<br/>sql/schema.sql]
    F --> G[Reconcile<br/>counts, coverage,<br/>checksums, samples]
    G --> H[Excel workbook +<br/>Streamlit sign-off<br/>+ metrics.json]
```

| Step | File | What it does |
|---|---|---|
| Download | `src/download.py` | Online Retail II from UCI (no login); Olist via the Kaggle CLI (your own token) |
| Extract | `src/extract.py` | Olist → `kna1_legacy.csv` (1 in 10 real customers, all their rows), `lfa1_legacy.csv` (all 3,095 sellers), `geo_reference.csv` (zip prefix → city/state); Online Retail II → `mara_legacy.csv` |
| Profile | `src/profile.py` | Per-field completeness / uniqueness / validity / shapes → `reports/profiling_report.html` |
| Rules | `config/rules.yaml` | Mandatory fields, zip format, 27 Brazilian UFs, address checks, obsolete cutoffs, dedup keys |
| Mapping | `config/mapping.yaml` | Legacy field → S/4HANA table/field, value maps, documented `not_in_source` gaps |
| Address | `src/address.py` | City matched to the zip prefix's cities: exact, rapidfuzz, or after removing extra text |
| Cleanse | `src/cleanse.py` | Trim, zip prefix to 5 digits, state upper case, UoM value map, standard city spelling |
| Validate | `src/rules.py` | Every failure → quarantine row with a reason code (never a silent drop) |
| Dedup | `src/dedup.py` | Exact-key groups + survivorship + golden record; location-only matcher for evaluation |
| Evaluate | `src/evaluate.py` | Real-data findings: city match rates, location matcher precision/recall vs `customer_unique_id` |
| Map | `src/mapping.py` | BUT000/BUT020/ADRC/BUT100 + CVI link tables, MARA/MAKT/MBEW |
| Load | `src/load.py`, `sql/schema.sql` | Portable DDL with primary keys; PostgreSQL or SQLite |
| Reconcile | `src/reconcile.py` | Count balance, id coverage, roles, CRC32 field checksums, 20-record sample comparison |
| Report | `src/report_excel.py` | Excel workbook: Summary, per-object sheets, Rejections, Duplicates, Sign-off |
| Dashboard | `app/dashboard.py` | Streamlit: reconciliation, rejections, duplicates, profiling, sign-off |
| Run all | `src/pipeline.py` | Orchestrates everything and writes `metrics.json` |

## Screenshots

| | |
|---|---|
| ![Reconciliation dashboard](docs/screenshots/01-reconciliation.png) **Reconciliation dashboard**: records in/loaded/quarantined/merged and checks per object | ![Rejected records](docs/screenshots/02-rejections.png) **Rejected records**: quarantine list filterable by object and reason |
| ![Excel workbook](docs/screenshots/03-excel-report.png) **Excel reconciliation workbook** (Summary sheet, conditional formatting) | ![Profiling report](docs/screenshots/04-profiling.png) **Profiling report** of the raw legacy extracts |
| ![Terminal run](docs/screenshots/05-terminal-run.png) **Terminal output** of a real `python -m src.pipeline` run | ![CI passing](docs/screenshots/06-ci-passing.png) **GitHub Actions**: ruff, pytest on PostgreSQL + SQLite, pipeline run, docker build |

How the images were made (all real captures, no mock-ups):
- Dashboard images and `demo.gif`: Playwright (Chromium) against the running Streamlit app; the GIF is the
  Playwright screen recording converted with ffmpeg (`scripts/capture_screenshots.py`).
- Excel image: no Excel/LibreOffice was available, so `scripts/render_excel.py` reads the generated
  `reports/reconciliation_report.xlsx` with openpyxl, copies cell styles, **evaluates the workbook's own conditional
  formatting rules** (cell-equals fills and data bars) and writes HTML, which Playwright captures.
- Terminal image: stdout of a real pipeline run saved to `reports/pipeline_run.log`, rendered in a `<pre>` page.
- CI image: Playwright capture of the public GitHub Actions run page after the run was green.

## Data sources and licences

| Used as | Dataset | Licence |
|---|---|---|
| Customers (KNA1-like), vendors (LFA1-like), address reference | **Brazilian E-Commerce Public Dataset by Olist**, Kaggle [`olistbr/brazilian-ecommerce`](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce): `olist_customers`, `olist_sellers`, `olist_geolocation` (+ order dates from `olist_orders` / `olist_order_items`) | **CC BY-NC-SA 4.0** (non-commercial, share-alike) |
| Materials (MARA/MAKT/MBEW-like) | **Online Retail II**, Daqing Chen (2019), UCI ML Repository [dataset 502](https://archive.ics.uci.edu/dataset/502/online+retail+ii); same data on Kaggle [`mashlyn/online-retail-ii-uci`](https://www.kaggle.com/datasets/mashlyn/online-retail-ii-uci) | **CC BY 4.0** |

- The derived extracts in `data/legacy/` are adaptations of these datasets and keep their licences
  (Olist-derived files: CC BY-NC-SA 4.0). Raw downloads are gitignored.
- Customer extract = a deterministic sample of 1 in 10 real customers (MD5 of `customer_unique_id`), keeping all of
  each customer's rows so real duplicate groups stay complete. Vendors and the address reference are complete.
- Materials: unit of measure (`SET`/`PAK`/`ST` from the description) and material type (digits → trading goods)
  are **derived by documented heuristics** in `src/extract.py`; the source has no such fields.
- CI uses the committed extracts (~2.5 MB) – no download, no Kaggle credentials.

## Mapping gaps

Olist is anonymised, so these S/4HANA fields stay **empty** (`not_in_source` in `config/mapping.yaml`); in a real
project they would come from the legacy system: `BUT000-NAME_FIRST/NAME_LAST` (customers), `BUT000-NAME_ORG1`
(vendors), `ADRC-STREET`, `ADRC-TEL_NUMBER` (ADR2), `ADRC-SMTP_ADDR` (ADR6), tax numbers (CPF/CNPJ), and the full
8-digit CEP (only the 5-digit prefix is published). `BUT000-BPEXT` is CHAR 20 but Olist ids are 32-character hashes,
so the legacy id lives in `CVI_CUST_LINK` / `CVI_VEND_LINK` (widened to 32). E-mail and phone rules are therefore
not configured (documented as not applicable in `config/rules.yaml`). There is no customer–vendor overlap that can be
justified from this data (no shared tax id or name), so no customer+vendor BP is created.

## How to run

```powershell
python -m venv .venv
.venv\Scripts\activate                      # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt

python -m src.pipeline                       # SQLite: data/migrateright.db, reports/, metrics.json
python scripts/render_metrics_docs.py        # refresh the numbers in README / RESUME_BULLETS
streamlit run app/dashboard.py               # http://localhost:8540
pytest -q ; ruff check .
```

Rebuild the extracts from the raw data (optional): `python -m src.download` (Olist needs your Kaggle token in
`~/.kaggle`), then `python -m src.extract`.

**PostgreSQL** – set `MIGRATERIGHT_DB_URL` (see `.env.example`), e.g.
`postgresql+psycopg2://migrateright:change_me@localhost:5450/migrateright`. With Docker:

```bash
docker compose up --build        # Postgres on localhost:5450, dashboard on http://localhost:8540
```

(The image is built by `docker build` in CI; the full pipeline + tests run against a PostgreSQL 16 service container
in CI. Locally this project was run with the SQLite fallback.)

Business users change behaviour only in `config/rules.yaml` and `config/mapping.yaml` – e.g. the obsolete cutoffs,
the city fuzzy threshold or the dedup key – and re-run.

## Limitations

- Simplified target: real S/4HANA has many more BP tables (BUT0BK bank, KNVV sales area, LFB1 company code, tax
  numbers in DFKKBPTAXNUM…); phone/e-mail would sit in ADR2/ADR6.
- Anonymised source: no names, streets, phones, e-mails or CPF/CNPJ, so identity matching is only possible on the
  `customer_unique_id` cross-reference; location-only matching is measured and rejected (see results).
- The geolocation reference is itself crowd-sourced and incomplete: some "ZIP_NOT_FOUND" records may be valid
  addresses that the reference lacks – they go to a review list, not to the bin.
- Obsolete cutoffs are business assumptions on a 2016–2018 (Olist) and 2009–2011 (Online Retail II) extract.
- This loads database tables; a real project would hand the cleansed files to SAP Migration Cockpit (LTMC/LTMOM)
  or the "Migrate Your Data" app, which runs SAP's own APIs and validations.

See [INTERVIEW_NOTES.md](INTERVIEW_NOTES.md) for 20 Q&As and [RESUME_BULLETS.md](RESUME_BULLETS.md).
