"""Write the numbers from metrics.json into README.md and RESUME_BULLETS.md.

README.md: replaces everything between <!-- METRICS:START --> and <!-- METRICS:END -->.
RESUME_BULLETS.md: rewritten completely.
So the docs never drift from the latest real run.

Usage:  python scripts/render_metrics_docs.py
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
m = json.loads((ROOT / "metrics.json").read_text(encoding="utf-8"))
obj, tot = m["objects"], m["totals"]
find = m["real_data_findings"]
loc = find["location_only_matcher_vs_unique_id"]
cities = find["city_standardisation"]
dups = find["customer_duplicates"]

LABEL = {"customer": "Customers (Olist customers → BP, role FLCU01)",
         "vendor": "Vendors (Olist sellers → BP, role FLVN01)",
         "material": "Materials (Online Retail II → MARA/MAKT/MBEW)"}


def reasons(o: str) -> str:
    return ", ".join(f"{rule} {pct} %" for rule, pct in obj[o]["rejected_pct_by_reason"].items())


rows = "\n".join(
    f"| {LABEL[o]} | {v['records_in']:,} | {v['records_loaded']:,} | {v['records_quarantined']:,} | "
    f"{v['rejected_pct']} % | {v['duplicates_merged']:,} | {v['recon_checks_passed']} |" for o, v in obj.items())
vendor_fixed = cities["vendor"]["fuzzy"]["records"] + cities["vendor"]["cleaned"]["records"]

block = f"""<!-- METRICS:START -->
| Object | Records in | Loaded | Quarantined | % rejected | Duplicates merged | Recon checks |
|---|---:|---:|---:|---:|---:|---:|
{rows}
| **Total** | **{tot['records_in']:,}** | **{tot['records_loaded']:,}** | **{tot['records_quarantined']:,}** | \
**{tot['quarantined_pct']} %** | **{tot['duplicates_merged']:,}** | \
**{m['reconciliation_checks_passed']}/{m['reconciliation_checks_total']} {m['overall_status']}** |

- **{tot['business_partners_created']:,} Business Partners** created ({obj['customer']['records_loaded']:,} customers,
  {obj['vendor']['records_loaded']:,} vendors) and {obj['material']['records_loaded']:,} products.
- **Rejected % of records in, by reason** (a record can fail several rules):
  customers: {reasons('customer')} · vendors: {reasons('vendor')} · materials: {reasons('material')}.
- **City standardisation** against Olist geolocation: customers {cities['customer']['exact']['pct']} % exact;
  vendors {cities['vendor']['exact']['pct']} % exact, **{vendor_fixed} corrected** by fuzzy match or by stripping
  extra text (`sao pauo`, `mogi das cruzes / sp`), {cities['vendor']['none']['records']} unmatched
  (`sp`, `bahia`, an e-mail address typed as the city…).
- **Real duplicates:** {dups['customer_id_rows']:,} customer rows belong to {dups['unique_customers']:,} real customers
  (`customer_unique_id`) → {obj['customer']['duplicates_merged']:,} merged (the rest of the {dups['duplicate_rows']}
  duplicate rows were already quarantined). Materials: {obj['material']['duplicates_merged']} codes that differ only
  in case (`85123A`/`85123a`).
- **Location-only duplicate matcher vs. the real id** (same zip prefix + fuzzy city ≥ 90 + same state):
  precision **{loc['precision_pct']} %**, recall **{loc['recall_pct']} %** ({loc['correct_pairs']} of
  {loc['true_duplicate_pairs']} true pairs found, {loc['pairs_proposed']:,} pairs proposed). Without a name, e-mail or
  CPF the address alone cannot tell people apart, so merging is done on `customer_unique_id` only.
<!-- METRICS:END -->"""

readme = ROOT / "README.md"
text = readme.read_text(encoding="utf-8")
readme.write_text(re.sub(r"<!-- METRICS:START -->.*?<!-- METRICS:END -->", lambda _: block, text, flags=re.S),
                  encoding="utf-8")

bullets = f"""# Resume bullets – MigrateRight

- Built a Python/SQL SAP ECC→S/4HANA migration case study on real Olist and Online Retail II data, loading \
{tot['records_loaded']:,} of {tot['records_in']:,} legacy records.
- Wrote YAML address rules against Brazilian geolocation data, quarantining {tot['records_quarantined']:,} records \
({tot['quarantined_pct']}%) with reason codes and no silent drops.
- Merged {tot['duplicates_merged']} real duplicates with survivorship and showed location-only matching reached only \
{loc['precision_pct']}% precision versus customer_unique_id.
- Delivered {m['reconciliation_checks_total']} automated reconciliation checks, an openpyxl sign-off workbook and \
Streamlit dashboard; CI tests PostgreSQL and SQLite.
"""
(ROOT / "RESUME_BULLETS.md").write_text(bullets, encoding="utf-8")
for line in bullets.splitlines():
    if line.startswith("- "):
        print(len(line[2:].split()), "words:", line[2:70])
