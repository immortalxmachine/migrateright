"""Reconciliation step: prove that nothing was lost or changed by accident.

For every object it checks, mostly with SQL against the loaded database:
  1. count     source rows (src_<object>) = rows in the legacy file
  2. balance   records_in = loaded + quarantined + merged
  3. coverage  every legacy id sits in exactly ONE bucket (loaded/quarantined/merged)
  4. target    rows in the target tables = number of survivors
  5. checksums per mapped field: filled count + CRC32 checksum, expected vs loaded
  6. sample    20 random records, legacy value vs target value, field by field
Results are stored in mig_recon_checks / mig_recon_summary / mig_recon_sample
and exported to Excel by src/report_excel.py.
"""

import numbers
import zlib

import pandas as pd
from sqlalchemy.engine import Engine

from src.load import read_sql, scalar
from src.mapping import build_rows

SAMPLE_SIZE = 20

# How to read the loaded records back, keyed by legacy id (one SQL per object)
ACTUAL_SQL = {
    "customer": """
        SELECT l.kunnr AS legacy_id, b.name_org1, b.name_org2, b.bu_group, a.street, a.city1,
               a.post_code1, a.country, a.tel_number, a.smtp_addr
        FROM tgt_cvi_cust_link l
        JOIN tgt_but000 b ON b.partner = l.partner
        JOIN tgt_but020 r ON r.partner = b.partner
        JOIN tgt_adrc a ON a.addrnumber = r.addrnumber""",
    "vendor": """
        SELECT l.lifnr AS legacy_id, b.name_org1, b.name_org2, b.bu_group, a.street, a.city1,
               a.post_code1, a.country, a.tel_number, a.smtp_addr
        FROM tgt_cvi_vend_link l
        JOIN tgt_but000 b ON b.partner = l.partner
        JOIN tgt_but020 r ON r.partner = b.partner
        JOIN tgt_adrc a ON a.addrnumber = r.addrnumber
        WHERE l.lifnr NOT IN (SELECT vendor_id FROM mig_shared_bp)""",
    "material": """
        SELECT m.bismt AS legacy_id, m.matnr, m.mtart, m.meins, t.maktx, w.stprs
        FROM tgt_mara m
        JOIN tgt_makt t ON t.matnr = m.matnr
        JOIN tgt_mbew w ON w.matnr = m.matnr""",
}
# Which target tables hold the compared columns (from config/mapping.yaml)
COMPARE_TABLES = {"customer": ["BUT000", "ADRC"], "vendor": ["BUT000", "ADRC"],
                  "material": ["MARA", "MAKT", "MBEW"]}
LOADED_IDS_SQL = {"customer": "SELECT kunnr AS id FROM tgt_cvi_cust_link",
                  "vendor": "SELECT lifnr AS id FROM tgt_cvi_vend_link",
                  "material": "SELECT bismt AS id FROM tgt_mara"}
ROLE = {"customer": "FLCU01", "vendor": "FLVN01"}
RAW_KEY = {"customer": "kunnr", "vendor": "lifnr", "material": "matnr"}   # key in src_<object>


def normalise(value) -> str:
    """Make values comparable across databases (numbers as 2-decimals text, None as '')."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, numbers.Number):
        return f"{float(value):.2f}"
    return str(value)


def checksum(values) -> tuple[int, str]:
    """(filled count, CRC32-based checksum) of a column, independent of row order."""
    texts = [normalise(v) for v in values]
    total = sum(zlib.crc32(t.encode("utf-8")) for t in texts) % (2**32)
    return sum(1 for t in texts if t), f"{total:08X}"


def expected_frame(survivors: pd.DataFrame, obj: str, mapping: dict) -> pd.DataFrame:
    """What the target SHOULD contain: survivors pushed through the mapping again."""
    spec = mapping["objects"][obj]["tables"]
    rows = []
    for row in survivors.to_dict("records"):
        out = {"legacy_id": row["LEGACY_ID"]}
        for table in COMPARE_TABLES[obj]:
            mapped = build_rows(row, spec[table], mapping["value_maps"],
                                {"partner": None, "address": None})
            out.update({col.lower(): val for col, val in mapped.items()})
        rows.append(out)
    return pd.DataFrame(rows)


def check(obj, name, expected, actual, detail=""):
    status = "PASS" if normalise(expected) == normalise(actual) else "FAIL"
    return {"object": obj, "check": name, "expected": normalise(expected),
            "actual": normalise(actual), "status": status, "detail": detail}


def reconcile_object(engine: Engine, obj: str, records_in: int, survivors: pd.DataFrame,
                     shared_ids: set, mapping: dict) -> tuple[list, pd.DataFrame]:
    """All checks for one object. Returns (check rows, sample comparison)."""
    checks = []
    src_count = scalar(engine, f"SELECT COUNT(*) FROM src_{obj}")
    checks.append(check(obj, "Source rows staged = legacy file rows", records_in, src_count))

    source_ids = set(read_sql(engine, f"SELECT {RAW_KEY[obj]} AS id FROM src_{obj}")["id"])
    loaded = set(read_sql(engine, LOADED_IDS_SQL[obj])["id"])
    quarantined = set(read_sql(
        engine, f"SELECT DISTINCT legacy_id AS id FROM mig_quarantine WHERE object = '{obj}'")["id"])
    merged = set(read_sql(
        engine, f"SELECT merged_id AS id FROM mig_merge_log WHERE object = '{obj}'")["id"])

    balance = len(loaded) + len(quarantined) + len(merged)
    checks.append(check(obj, "Records in = loaded + quarantined + merged", records_in, balance,
                        f"{len(loaded)} loaded + {len(quarantined)} quarantined + {len(merged)} merged"))
    unaccounted = source_ids - loaded - quarantined - merged
    checks.append(check(obj, "Legacy ids not accounted for", 0, len(unaccounted),
                        ", ".join(sorted(unaccounted)[:10])))
    overlap = (loaded & quarantined) | (loaded & merged) | (quarantined & merged)
    checks.append(check(obj, "Legacy ids in more than one bucket", 0, len(overlap),
                        ", ".join(sorted(overlap)[:10])))
    checks.append(check(obj, "Target rows = survivors", len(survivors), len(loaded)))

    if obj in ROLE:
        roles = scalar(engine, f"SELECT COUNT(*) FROM tgt_but100 WHERE rltyp = '{ROLE[obj]}'")
        checks.append(check(obj, f"BP role {ROLE[obj]} assigned", len(survivors), roles))
    if obj == "vendor":
        both = scalar(engine, """SELECT COUNT(*) FROM mig_shared_bp s
                                 JOIN tgt_but100 c ON c.partner = s.partner AND c.rltyp = 'FLCU01'
                                 JOIN tgt_but100 v ON v.partner = s.partner AND v.rltyp = 'FLVN01'""")
        checks.append(check(obj, "Shared customer/vendor BPs carry both roles", len(shared_ids), both,
                            "one Business Partner, two roles (CVI)"))

    # ---- field-level checksums: expected (transformation output) vs loaded (SQL)
    expected = expected_frame(survivors[~survivors["LEGACY_ID"].isin(shared_ids)], obj, mapping)
    actual = read_sql(engine, ACTUAL_SQL[obj])
    for col in [c for c in actual.columns if c != "legacy_id"]:
        exp_n, exp_sum = checksum(expected[col])
        act_n, act_sum = checksum(actual[col])
        checks.append(check(obj, f"Checksum {col}", f"{exp_n}/{exp_sum}", f"{act_n}/{act_sum}",
                            "filled values / CRC32 sum"))
    if obj == "material":
        exp_total = round(pd.to_numeric(expected["stprs"]).sum(), 2)
        act_total = round(pd.to_numeric(actual["stprs"]).sum(), 2)
        checks.append(check(obj, "Sum of standard prices (MBEW-STPRS)", exp_total, act_total))

    sample = sample_comparison(engine, obj, expected, actual)
    mismatches = int((sample["result"] == "MISMATCH").sum()) if not sample.empty else 0
    checks.append(check(obj, f"Sample of {SAMPLE_SIZE} records: field mismatches", 0, mismatches))
    return checks, sample


def sample_comparison(engine, obj, expected, actual) -> pd.DataFrame:
    """Field-by-field: raw legacy value vs expected (cleansed) vs value in the target."""
    if expected.empty:
        return pd.DataFrame()
    ids = expected["legacy_id"].sample(min(SAMPLE_SIZE, len(expected)), random_state=7)
    raw = read_sql(engine, f"SELECT * FROM src_{obj}")
    raw = raw.set_index(RAW_KEY[obj], drop=False)
    exp = expected.set_index("legacy_id")
    act = actual.set_index("legacy_id")
    # target column -> legacy column, for showing the raw value
    legacy_of = {"name_org1": "name1", "name_org2": "name2", "bu_group": "ktokd" if obj == "customer" else "ktokk",
                 "street": "stras", "city1": "ort01", "post_code1": "pstlz", "country": "land1",
                 "tel_number": "telf1", "smtp_addr": "email", "matnr": "matnr", "mtart": "mtart",
                 "meins": "meins", "maktx": "maktx", "stprs": "stprs"}
    rows = []
    for legacy_id in ids:
        for col in act.columns:
            legacy_val = raw.at[legacy_id, legacy_of[col]] if legacy_id in raw.index else None
            exp_val = normalise(exp.at[legacy_id, col])
            act_val = normalise(act.at[legacy_id, col]) if legacy_id in act.index else "<missing>"
            if exp_val != act_val:
                result = "MISMATCH"
            elif normalise(legacy_val) == act_val:
                result = "MATCH"
            else:
                result = "TRANSFORMED"      # changed on purpose by cleansing/mapping
            rows.append({"object": obj, "legacy_id": legacy_id, "field": col,
                         "legacy_value": normalise(legacy_val), "target_value": act_val,
                         "result": result})
    return pd.DataFrame(rows)


def reason_breakdown(quarantine: pd.DataFrame, records_in: dict) -> pd.DataFrame:
    """Records per rejection reason and % of records in (a record can have several reasons)."""
    if quarantine.empty:
        return pd.DataFrame(columns=["object", "rule", "records", "pct_of_records_in"])
    grouped = (quarantine.groupby(["object", "rule"])["legacy_id"].nunique()
               .reset_index(name="records"))
    grouped["pct_of_records_in"] = [
        round(100 * n / records_in[o], 2) for o, n in zip(grouped["object"], grouped["records"])]
    return grouped.sort_values(["object", "records"], ascending=[True, False]).reset_index(drop=True)


def summarise(checks: pd.DataFrame, counts: dict) -> pd.DataFrame:
    """One line per object for the sign-off summary."""
    rows = []
    for obj, c in counts.items():
        obj_checks = checks[checks["object"] == obj]
        passed = int((obj_checks["status"] == "PASS").sum())
        rows.append({
            "object": obj, "records_in": c["records_in"], "loaded": c["loaded"],
            "quarantined": c["quarantined"], "duplicates_merged": c["merged"],
            "shared_bp": c.get("shared_bp", 0),
            "rejected_pct": round(100 * c["quarantined"] / c["records_in"], 2),
            "checks_passed": passed, "checks_total": len(obj_checks),
            "status": "PASS" if passed == len(obj_checks) else "FAIL",
        })
    return pd.DataFrame(rows)
