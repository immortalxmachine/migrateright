# MigrateRight

**SAP ECC → S/4HANA master-data migration toolkit**: profiling, rule-based cleansing, Business Partner mapping,
fuzzy de-duplication, loading into S/4HANA-shaped tables, and reconciliation reports (Excel + Streamlit) that a
business user can sign off.

![Streamlit sign-off flow](docs/screenshots/demo.gif)

[![CI](https://github.com/immortalxmachine/migrateright/actions/workflows/ci.yml/badge.svg)](https://github.com/immortalxmachine/migrateright/actions/workflows/ci.yml)

## Results of the latest run (from `metrics.json`)

| Object | Records in | Loaded | Quarantined | % rejected | Duplicates merged | Recon checks |
|---|---:|---:|---:|---:|---:|---:|
| Customers (KNA1 → BP, synthetic) | 1,290 | 974 | 226 | 17.52 % | 90 | 16/16 PASS |
| Vendors (LFA1 → BP, synthetic) | 450 | 344 | 76 | 16.89 % | 30 | 17/17 PASS |
| Materials (MARA/MAKT → product, real data) | 5,304 | 3,927 | 1,266 | 23.87 % | 111 | 12/12 PASS |
| **Total** | **7,044** | **5,245** | **1,568** | **22.26 %** | **231** | **45/45 PASS** |

- **1,298 Business Partners** created from 1,318 surviving customer/vendor records: **20** companies that were both
  customer and vendor became **one BP with two roles** (FLCU01 + FLVN01).
- **Rejected % by reason** (a record can fail several rules):
  customers: OBSOLETE 5.58 %, MISSING_MANDATORY 3.72 %, INVALID_PHONE 3.26 %, INVALID_POSTAL_CODE 2.79 %,
  INVALID_EMAIL 2.33 %, INVALID_COUNTRY 0.78 % · vendors: OBSOLETE 5.33 %, INVALID_PHONE 3.78 %,
  MISSING_MANDATORY 3.56 %, INVALID_POSTAL_CODE 2.67 %, INVALID_EMAIL 2.22 %, INVALID_COUNTRY 0.89 % ·
  materials: OBSOLETE (not sold in last 12 months) 23.27 %, MISSING_PRICE 7.05 %, MISSING_MANDATORY
  (no description) 6.69 %, NON_PRODUCT (postage, fees, tests) 0.51 %, INVALID_DESCRIPTION 0.26 %.
- **Rule coverage on the synthetic data**: all 302 injected rejectable issues were quarantined, 200/200 country
  variants (`UK`, `Germany`, `DEU`…) were auto-fixed by the value map, and 120/120 injected duplicate pairs were
  merged with no false merges. An earlier rule (name ≥ 90 + only **one** equal support field) made 2 false
  merges ("Pinecrest *Lighting* Supplies" vs "Pinecrest *Living* & Supplies"); requiring **two** equal fields
  fixed that. These numbers prove the rules catch the issues *we injected*; they are not a real-world accuracy claim.

## Pipeline

```mermaid
flowchart LR
    A[Extract<br/>legacy ECC extracts<br/>KNA1 / LFA1 / MARA] --> B[Profile<br/>completeness, uniqueness,<br/>validity, shapes]
    B --> C[Cleanse + validate<br/>rules.yaml<br/>failures -> quarantine]
    C --> D[De-duplicate<br/>rapidfuzz + survivorship<br/>-> merge log]
    D --> E[Map<br/>mapping.yaml<br/>BP: BUT000/BUT020/ADRC/BUT100<br/>Product: MARA/MAKT/MBEW]
    E --> F[Load<br/>PostgreSQL or SQLite<br/>sql/schema.sql]
    F --> G[Reconcile<br/>counts, coverage,<br/>checksums, samples]
    G --> H[Excel workbook +<br/>Streamlit sign-off<br/>+ metrics.json]
```

| Step | File | What it does |
|---|---|---|
| Download | `src/download.py` | Fetches Online Retail II from UCI (no login), resumes on dropped connections |
| Extract | `src/extract.py` | Condenses ~1M invoice lines into 5,304 legacy material records (`data/legacy/mara_legacy.csv`) |
| Synthetic data | `src/generate_synthetic.py` | KNA1/LFA1-style records + a ground-truth log of every injected issue |
| Profile | `src/profile.py` | Per-field completeness / uniqueness / validity / shapes → `reports/profiling_report.html` |
| Rules | `config/rules.yaml` | Mandatory fields, regex formats, postcode per country, allowed values, obsolete cutoff, dedup keys |
| Mapping | `config/mapping.yaml` | Legacy field → S/4HANA table/field, value maps (country, UoM, account group) |
| Cleanse | `src/cleanse.py` | Trim, value maps, postcode spacing, phone → E.164 |
| Validate | `src/rules.py` | Applies rules.yaml; every failure becomes a quarantine row with a reason code |
| Dedup | `src/dedup.py` | Blocking by country, rapidfuzz `token_sort_ratio`, union-find clusters, survivorship + golden record |
| Map | `src/mapping.py` | Builds BUT000/BUT020/ADRC/BUT100/CVI links and MARA/MAKT/MBEW; one BP for customer+vendor |
| Load | `src/load.py`, `sql/schema.sql` | Portable DDL with primary keys; loads PostgreSQL or SQLite |
| Reconcile | `src/reconcile.py` | Count balance, id coverage, role checks, CRC32 field checksums, 20-record sample comparison |
| Report | `src/report_excel.py` | Excel workbook: Summary, per-object sheets, Rejections, Duplicates, Sign-off, conditional formatting |
| Dashboard | `app/dashboard.py` | Streamlit views for reconciliation, rejections, duplicates, profiling and sign-off |
| Run all | `src/pipeline.py` | Orchestrates everything and writes `metrics.json` |

## Screenshots

| | |
|---|---|
| ![Reconciliation dashboard](docs/screenshots/01-reconciliation.png) **Reconciliation dashboard**: records in/loaded/quarantined/merged and checks per object | ![Rejected records](docs/screenshots/02-rejections.png) **Rejected records**: quarantine list filterable by object and reason |
| ![Excel workbook](docs/screenshots/03-excel-report.png) **Excel reconciliation workbook** (Summary sheet, conditional formatting) | ![Profiling report](docs/screenshots/04-profiling.png) **Profiling report** of the raw legacy data |
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

- **Materials – real data.** *Online Retail II* (Daqing Chen, 2019), UCI Machine Learning Repository, dataset 502,
  <https://archive.ics.uci.edu/dataset/502/online+retail+ii>, licensed **CC BY 4.0**. The same data is on Kaggle as
  [mashlyn/online-retail-ii-uci](https://www.kaggle.com/datasets/mashlyn/online-retail-ii-uci). Real stock codes
  and descriptions are used as the legacy material master; the unit of measure (`SET`/`PAK`/`ST` from the
  description text) and material type (digits → trading goods) are **derived by documented heuristics** in
  `src/extract.py` because the source has no such fields. The 45 MB raw file is not committed; run
  `python -m src.download` then `python -m src.extract` to rebuild `data/legacy/mara_legacy.csv`.
- **Customers and vendors – SYNTHETIC.** ⚠️ Every KNA1/LFA1 record is fake, generated by
  `src/generate_synthetic.py` (seed 42): random word-combination company names, e-mail domains on the reserved
  `.example` TLD, random phone numbers. Injected issues are logged in `data/legacy/injected_issues.csv`.
- **CI** uses the committed legacy CSVs (≈ 700 KB), so it never downloads the dataset.

## How to run

```powershell
python -m venv .venv
.venv\Scripts\activate                      # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt

python -m src.pipeline                       # SQLite: data/migrateright.db, reports/, metrics.json
streamlit run app/dashboard.py               # http://localhost:8540
pytest -q ; ruff check .
```

Optional: rebuild the inputs: `python -m src.download`, `python -m src.extract`, `python -m src.generate_synthetic`.

**PostgreSQL** – set `MIGRATERIGHT_DB_URL` (see `.env.example`), e.g.
`postgresql+psycopg2://migrateright:change_me@localhost:5450/migrateright`. With Docker:

```bash
docker compose up --build        # Postgres on localhost:5450, dashboard on http://localhost:8540
```

(The Docker files are tested by `docker build` in CI; the full pipeline + tests run against a PostgreSQL 16 service
container in CI. Locally this project was run with the SQLite fallback.)

Business users change behaviour in `config/rules.yaml` and `config/mapping.yaml` only – e.g. move the obsolete
cutoff, add a country spelling to the value map, or tighten the duplicate threshold – and re-run.

## Limitations

- Simplified target: real S/4HANA has many more BP tables (BUT0BK bank, KNVV sales area, LFB1 company code…);
  phone/e-mail sit in ADR2/ADR6, here they are columns on ADRC.
- Customer/vendor records are synthetic, so detection rates measure rule coverage, not real-world accuracy.
- Duplicate matching compares all pairs inside a country block (O(n²)); millions of records need tighter blocking.
- Survivorship is record-level ("most complete, newest") plus gap filling; field-level trust rules are not modelled.
- This loads database tables; a real project would hand the cleansed files to SAP Migration Cockpit (LTMC/LTMOM)
  or the "Migrate Your Data" app, which runs SAP's own BAPIs and validations.

See [INTERVIEW_NOTES.md](INTERVIEW_NOTES.md) for 20 Q&As and [RESUME_BULLETS.md](RESUME_BULLETS.md).
