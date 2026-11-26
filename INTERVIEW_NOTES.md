# MigrateRight – interview notes (20 Q&As)

Case study: a Brazilian retailer's customer and vendor master (real Olist data) and a UK retailer's product master
(real Online Retail II data) migrated from legacy ECC-style extracts to S/4HANA. Numbers are from the committed
`metrics.json`: 18,330 legacy records in, 16,167 loaded, 1,719 quarantined (9.38 %), 444 duplicates merged,
12,240 Business Partners, 52/52 reconciliation checks passed.

### SAP background

**1. What changes between SAP ECC and S/4HANA for master data?**
S/4HANA runs only on HANA and simplifies the data model. For master data the big change is the mandatory
**Business Partner (BP)**: customers (KNA1) and vendors (LFA1) are maintained through a BP with roles. Material
numbers can be 40 characters (ECC: 18). The target tables are modelled in `sql/schema.sql`
(BUT000, BUT020, ADRC, BUT100, CVI link tables, MARA, MAKT, MBEW).

**2. Why does the Business Partner replace separate customer and vendor masters?**
One legal entity is often both customer and vendor; in ECC that meant two records whose names and addresses drift
apart. The BP holds general data and address once and adds **roles** (FLCU01 customer, FLVN01 vendor).
Customer-Vendor Integration (CVI) keeps the legacy numbers linked (CVI_CUST_LINK / CVI_VEND_LINK) – see
`map_business_partners()` in `src/mapping.py`. In this data there is no shared tax id or name between Olist
customers and sellers, so I did **not** claim any customer+vendor BP; in a real Brazilian project the CNPJ/CPF tax
number would be the key for that.

**3. What are the phases of a data-migration project?**
Scope → extract → profile → cleanse → map/transform → load (mock loads, dress rehearsal, cut-over) → reconcile and
sign off. `src/pipeline.py` implements one full mock-load cycle and is re-run after every rule change.

**4. What does SAP Migration Cockpit (LTMC/LTMOM, "Migrate Your Data") do, and how does this relate?**
It is SAP's standard tool: predefined migration objects (Customer, Supplier, Product…), file or staging-table
templates, field/value mapping, simulation, and posting through SAP APIs with SAP's own checks; LTMOM adjusts the
objects. MigrateRight covers what happens before and after it – profiling, cleansing, dedup and an independent
reconciliation. In a real project its output would fill the cockpit's staging tables.

### Data and profiling

**5. Why Olist and Online Retail II, and what did you NOT have?**
Both are real, public and licensed (Olist CC BY-NC-SA 4.0, Online Retail II CC BY 4.0). Olist is anonymised: no
names, streets, phones, e-mails or CPF/CNPJ. Those S/4HANA fields are marked `not_in_source` in
`config/mapping.yaml` and left empty – `unmapped_fields()` lists 14 of them in `metrics.json`. Inventing them would
make the reconciliation meaningless.

**6. What does profiling measure and what did it show?**
`profile_dataframe()` in `src/profile.py` on the raw extract: completeness, uniqueness, validity against the rules,
"shapes" (`99999`) and top values. It showed the seller city field is free text: `sp`, `sao paulo / sp`,
`rio de janeiro \rio de janeiro`, even an e-mail address; in Online Retail II 355 stock codes have no description and
374 never had a positive price.

**7. How did you make the 99k-row customer file small enough to commit for CI?**
`in_sample()` in `src/extract.py` keeps 1 in 10 real customers by MD5 of `customer_unique_id`. Hashing the person
id (not the row) keeps whole duplicate groups together, and the sample is identical on every machine. CI uses the
committed extracts, so it needs no Kaggle credentials.

### Rules, cleansing and address validation

**8. Why rules in YAML instead of code?**
So the business owns them: obsolete cutoffs, the 27 valid UFs, the city fuzzy threshold and the dedup key live in
`config/rules.yaml`; `validate()` in `src/rules.py` just loops over what is configured.

**9. How does address validation work?**
`src/address.py` builds a reference from `olist_geolocation` (zip prefix → cities, state). For each record:
exact city match for that zip prefix; else rapidfuzz ratio ≥ 85 (`sao pauo` → São Paulo); else retry on the text
before `/ - , (` (`mogi das cruzes / sp`). Then `check_address()` quarantines ZIP_NOT_FOUND, ZIP_STATE_MISMATCH
(e.g. SP typed for a Santa Catarina zip) and CITY_ZIP_MISMATCH. Vendors: 96.9 % exact, 47 auto-corrected,
49 unmatched.

**10. Cleansing vs validation?**
Cleansing (`src/cleanse.py`) only fixes what is safe: whitespace, zip prefix back to 5 digits, state upper case,
UoM value map, the reference spelling of the city. Validation judges the result. A city we cannot match is not
"fixed" by guessing – it goes to quarantine.

**11. Why a quarantine table instead of dropping bad records?**
Silent drops are the classic migration failure. Every failure is a row in `mig_quarantine` (object, legacy id,
rule, field, value), and reconciliation proves `records_in = loaded + quarantined + merged`.

**12. How do you handle obsolete records?**
`check_obsolete()`: no activity since a cutoff from rules.yaml. Vendors with no sale since 2017-07-01 (303, 9.79 %),
customers with no order since 2017-01-01 (39), materials not sold in the last 12 months (1,234, 23.27 %). It is a
business decision, so it is configuration.

### Duplicates and survivorship

**13. Where do the real duplicates come from?**
Olist creates a new `customer_id` per order; `customer_unique_id` identifies the person. In the extract 9,931 rows
belong to 9,593 people → 333 merged by `deduplicate_exact()` in `src/dedup.py` (5 more duplicate rows were already
quarantined). Materials: 111 codes that differ only in case (`85123A` / `85123a`).

**14. What is survivorship here?**
`pick_survivor()`: highest value of the configured fields wins – newest order for customers (most recent address),
most sales history for materials – ties go to the lowest legacy id. `golden_record()` fills the survivor's empty
fields from the other duplicates. Merged ids are logged in `mig_merge_log`, never deleted.

**15. Could you have found the duplicates without customer_unique_id? Show me numbers.**
`location_match_pairs()` (same zip prefix + rapidfuzz city ≥ 90 + same state) was measured against the real id in
`src/evaluate.py`: **recall 90.58 %, precision 3.83 %** – 327 of 361 true pairs found but 8,530 pairs proposed.
Many different people live in the same zip prefix. Without a name, e-mail or CPF, merging on location would destroy
thousands of real customers, so the rule merges only on the cross-reference id. `test_location_matcher_has_false_positives`
locks this in.

**16. When would fuzzy matching be the right tool?**
On attributes that identify an entity: names, street + house number, e-mails, tax ids – with blocking, a score
threshold, at least two agreeing fields, and a manual review band for borderline scores. Here rapidfuzz is used where
it is safe: correcting city names against a closed reference list.

### Mapping, load and reconciliation

**17. Walk me through one customer's mapping.**
`config/mapping.yaml` → new 10-digit partner and address numbers; BUT000 (BU_TYPE 1 = person, BU_GROUP BPCU,
CRDAT = first order date; names empty, not in source); BUT020 partner→address; ADRC (CITY1 = standardised city,
POST_CODE1 = 5-digit CEP prefix, REGION = UF, COUNTRY = BR); BUT100 role FLCU01; CVI_CUST_LINK keeps the 32-char
legacy id (BPEXT is only CHAR 20).

**18. What exactly does reconciliation check?**
`reconcile_object()` in `src/reconcile.py`: staged rows = file rows; records in = loaded + quarantined + merged;
no legacy id unaccounted for or in two buckets; target rows = survivors; roles assigned; per-field filled count +
CRC32 checksum (expected transformation output vs data read back with SQL joins); sum of standard prices; a
20-record sample labelled MATCH / TRANSFORMED / CONSTANT / NOT_IN_SOURCE / MISMATCH. 52/52 passed, on SQLite and on
PostgreSQL in CI.

**19. How do you know the reconciliation would catch a problem?**
`test_reconciliation_detects_a_lost_record` deletes one loaded material and asserts the balance and coverage checks
turn FAIL. A check that can never fail is worthless.

**20. Limitations and next steps?**
Simplified target (no bank, sales-area, company-code or tax-number tables); anonymised source, so identity matching
relies on the cross-reference id; the geolocation reference is incomplete, so ZIP_NOT_FOUND records need human
review rather than rejection; obsolete cutoffs are assumptions. Next: generate Migration Cockpit staging files,
add a review queue in the dashboard to release quarantined records, and add CPF/CNPJ check-digit rules when a source
has tax numbers.
