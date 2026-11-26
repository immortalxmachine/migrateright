# MigrateRight – interview notes (20 Q&As)

Numbers quoted are from the committed `metrics.json` (7,044 legacy records in, 5,245 loaded, 1,568 quarantined,
231 duplicates merged, 45/45 reconciliation checks passed).

### SAP background

**1. What changes between SAP ECC and S/4HANA for master data?**
S/4HANA runs only on the HANA database and simplifies the data model. For master data the big change is that the
**Business Partner (BP)** is mandatory: customers (KNA1) and vendors (LFA1) are no longer maintained directly but
through a BP with roles. Material numbers can be 40 characters (ECC: 18). In this project the targets are modelled
in `sql/schema.sql` (BUT000, BUT020, ADRC, BUT100, CVI link tables, MARA, MAKT, MBEW).

**2. Why does the Business Partner replace separate customer and vendor masters?**
One legal entity often is both customer and vendor. In ECC that meant two records with duplicated names and
addresses that drift apart. The BP holds general data and address once (BUT000/ADRC) and adds **roles**
(FLCU01 customer, FLVN01 vendor). Customer-Vendor Integration (CVI) keeps the old KNA1/LFA1 numbers linked
(CVI_CUST_LINK/CVI_VEND_LINK). See `map_business_partners()` in `src/mapping.py`: 20 companies that existed as
both a customer and a vendor became 20 BPs with two roles, so 1,318 survivors → 1,298 BPs.

**3. What are the phases of a data-migration project?**
Typical: *analyse/scope* (which objects, which records are in scope) → *extract* → *profile* → *cleanse* →
*map/transform* → *load* (mock loads 1, 2, 3, dress rehearsal, cut-over) → *reconcile and sign off*. MigrateRight
implements one full mock-load cycle in `src/pipeline.py` and is designed to be re-run after every rule change.

**4. What does SAP Migration Cockpit (LTMC/LTMOM, "Migrate Your Data") do, and how does this relate?**
Migration Cockpit is SAP's standard tool: predefined *migration objects* (e.g. "Customer", "Supplier",
"Product"), file or staging-table templates, field/value mapping, simulation, and posting through SAP APIs with
SAP's own validations. LTMOM lets you adjust the objects. MigrateRight covers what happens **before and after**
the cockpit: profiling, cleansing, dedup and an independent reconciliation. In a real project its cleansed output
would fill the cockpit's staging tables instead of the simplified tables used here.

### Profiling

**5. What do you profile and why before cleansing?**
`profile_dataframe()` in `src/profile.py` measures per field: completeness, distinct values/uniqueness, validity
against the rules (regex or allowed values), the most frequent "shapes" (`SW1A 1AA` → `AA9A 9AA`) and top values.
It runs on the **raw** extract so the business sees the real starting point – e.g. LAND1 was only 87.5 % valid
before value mapping because of `UK`, `Germany`, `DEU`.

**6. What did profiling reveal in the real Online Retail II data?**
355 stock codes never had a description (MISSING_MANDATORY), 374 never had a positive price, 173 codes differed
only in case (`85123A` vs `85123a`), and some "descriptions" were stock-adjustment notes (`damaged`,
`wet/rusty`) – caught by the `INVALID_DESCRIPTION` regex in `config/rules.yaml`.

### Rules and cleansing

**7. Why put rules in YAML instead of code?**
So the business can own them. A data owner can change the obsolete cutoff, add a mandatory field or a country
spelling in `config/rules.yaml` / `config/mapping.yaml` and re-run – no developer, no code review of Python.
`validate()` in `src/rules.py` just loops over whatever is configured.

**8. What is the difference between cleansing and validation here?**
Cleansing (`src/cleanse.py`) fixes only what is safe to fix automatically: whitespace, value maps (`UK` → `GB`,
`ST` → `PC`), postcode spacing, phone to E.164. Validation (`src/rules.py`) then *judges* the cleansed value.
Result: 200/200 injected country variants were fixed and loaded rather than rejected.

**9. Why a quarantine table instead of dropping bad records?**
Silent drops are the classic migration failure – nobody can explain the missing records at go-live.
Every failure is written to `mig_quarantine` with object, legacy id, rule, field and value, and reconciliation
proves `records_in = loaded + quarantined + merged`. The quarantine list goes back to the data owners to fix in
ECC or to accept as out of scope (e.g. OBSOLETE).

**10. How do you handle obsolete records?**
`check_obsolete()` in `src/rules.py`: deletion flag `LOEVM = 'X'` or no activity since a cutoff date from
rules.yaml. For materials the cutoff is "not sold in the last 12 months of the extract" → 1,234 materials
(23.27 %) not migrated. That's a business decision, so it's a config value, not code.

### De-duplication

**11. How does the fuzzy matching work?**
`find_duplicate_pairs()` in `src/dedup.py`: (1) **blocking** – only compare records in the same country;
(2) **match key** – lower case, remove punctuation and legal suffixes (`Ltd`, `GmbH`, `S.A.R.L.`), also a
truncated last word (`Limite`) because ECC names are cut at 35 chars; (3) rapidfuzz `token_sort_ratio` ≥ 90;
(4) at least **two** supporting fields equal (city, postcode, e-mail, phone).

**12. Why two supporting fields? Show me a false positive.**
With one supporting field the run produced 2 false merges, e.g. "Pinecrest Lighting Supplies Ltd" vs
"Pinecrest Living & Supplies Ltd" (score 92, same city London, different postcodes). Two fields gave
120/120 injected pairs found and 0 false merges. `test_different_companies_not_merged` in `tests/test_dedup.py`
locks this in. Thresholds are always a precision/recall trade-off; borderline scores should go to a review queue.

**13. What is survivorship?**
Deciding which record of a duplicate group becomes the master. `pick_survivor()`: most complete record first,
then newest `ERDAT`, then lowest legacy number (deterministic). `golden_record()` then fills the survivor's empty
fields from the other duplicates. Merged ids are logged in `mig_merge_log`, never deleted.

**14. Why union-find?**
Pairs are not groups: A~B and B~C means A, B and C are one company even if A and C score below the threshold.
`UnionFind` in `src/dedup.py` turns pairs into clusters in near-linear time.

### Mapping and load

**15. Walk me through the mapping of one customer.**
`config/mapping.yaml` → `map_business_partners()`: new partner number (10 digits) and address number;
BUT000 (BU_TYPE 2 = organisation, BU_GROUP from KTOKD via value map, NAME_ORG1, BPEXT = legacy KUNNR),
BUT020 (partner→address), ADRC (street, city, postcode, country, phone, e-mail), BUT100 role FLCU01 and a
CVI_CUST_LINK row. Materials: MARA (MATNR upper case, BISMT = old number as typed), MAKT (SPRAS E), MBEW price.

**16. Why load into a schema with primary keys?**
`sql/schema.sql` defines PKs (partner, address, matnr+spras…). If dedup or mapping created two BPs with the
same number, the load fails loudly instead of creating bad data. The same DDL runs on PostgreSQL (CI) and SQLite
(local fallback) – column names are lower case to avoid quoting differences.

### Reconciliation

**17. What exactly does reconciliation check?**
`reconcile_object()` in `src/reconcile.py`, per object: staged source rows = file rows; records in = loaded +
quarantined + merged; no legacy id unaccounted for; no id in two buckets; target rows = survivors; roles
assigned; shared BPs carry both roles; per-field filled count + CRC32 checksum (expected transformation output vs
data read back with SQL joins); sum of standard prices; a 20-record field-by-field sample labelled
MATCH / TRANSFORMED / MISMATCH. 45/45 passed.

**18. How do you know the reconciliation would catch a problem?**
`test_reconciliation_detects_a_lost_record` deletes one loaded material and asserts the balance and coverage checks
turn FAIL. A check that can never fail is worthless.

**19. What does the business actually sign off?**
The Excel workbook (`src/report_excel.py`): Summary (counts, % rejected, PASS/FAIL with conditional formatting,
rejection reasons with data bars), one sheet per object with checks and sample comparison, full Rejections and
Duplicates lists, and a Sign-off sheet. The Streamlit dashboard shows the same data and records sign-offs in
`mig_signoff`.

### Limitations

**20. What are the limitations and what would you do next?**
Simplified target tables (no bank, sales-area or company-code data; phone/e-mail on ADRC instead of ADR2/ADR6);
synthetic customers/vendors so detection rates show rule coverage, not field accuracy; O(n²) comparison inside a
country block; record-level survivorship only. Next: tighter blocking (postcode prefix / phonetic keys), a manual
review queue for match scores 85–95, field-level survivorship (trust by source), and generating Migration
Cockpit staging-table files instead of loading simplified tables.
