"""Validation step: apply config/rules.yaml to cleansed records.

Every failed check becomes one row in the quarantine list:
    object, legacy_id, rule, field, value
A record with at least one failure is NOT loaded. Nothing is silently dropped:
reconciliation later proves  records_in = loaded + quarantined + merged.
"""

import re

import pandas as pd

QUARANTINE_COLUMNS = ["object", "legacy_id", "rule", "field", "value"]


def _issue(obj, legacy_id, rule, field, value):
    return {"object": obj, "legacy_id": legacy_id, "rule": rule, "field": field,
            "value": None if value is None else str(value)[:255]}


def check_mandatory(df, obj, key, fields):
    """Mandatory field empty -> MISSING_MANDATORY."""
    issues = []
    for field in fields:
        for legacy_id in df.loc[df[field].isna(), key]:
            issues.append(_issue(obj, legacy_id, "MISSING_MANDATORY", field, None))
    return issues


def check_formats(df, obj, key, formats):
    """Filled field not matching its regex -> the reason from the rule (e.g. INVALID_EMAIL)."""
    issues = []
    for field, spec in formats.items():
        pattern = re.compile(spec["regex"])
        for legacy_id, value in zip(df[key], df[field]):
            if value is not None and not pattern.fullmatch(str(value)):
                issues.append(_issue(obj, legacy_id, spec["reason"], field, value))
    return issues


def check_address(df, obj, key, spec):
    """Zip prefix / state / city against the geolocation reference (columns added by cleanse).

    ZIP_NOT_FOUND       zip prefix is not in the reference at all
    ZIP_STATE_MISMATCH  the zip prefix belongs to a different state (UF)
    CITY_ZIP_MISMATCH   the city could not be matched to a city of that zip prefix
    """
    issues = []
    zip_f, state_f, city_f = spec["zip_field"], spec["state_field"], spec["city_field"]
    for legacy_id, zip_prefix, state, city, geo_state, match in zip(
            df[key], df[zip_f], df[state_f], df[city_f], df["GEO_REGIO"], df["CITY_MATCH"]):
        if zip_prefix is None:
            continue                                   # reported as MISSING_MANDATORY
        if geo_state is None:
            issues.append(_issue(obj, legacy_id, "ZIP_NOT_FOUND", zip_f, zip_prefix))
            continue
        if state is not None and state != geo_state:
            detail = f"{state} (zip {zip_prefix} is {geo_state})"
            issues.append(_issue(obj, legacy_id, "ZIP_STATE_MISMATCH", state_f, detail))
        if city is not None and match == "none":
            issues.append(_issue(obj, legacy_id, "CITY_ZIP_MISMATCH", city_f, city))
    return issues


def check_max_length(df, obj, key, limits):
    issues = []
    for field, limit in limits.items():
        for legacy_id, value in zip(df[key], df[field]):
            if value is not None and len(str(value)) > limit:
                issues.append(_issue(obj, legacy_id, "FIELD_TOO_LONG", field, value))
    return issues


def check_allowed_values(df, obj, key, allowed):
    issues = []
    for field, spec in allowed.items():
        values = set(spec["values"])
        for legacy_id, value in zip(df[key], df[field]):
            if value is not None and value not in values:
                issues.append(_issue(obj, legacy_id, spec["reason"], field, value))
    return issues


def check_min_value(df, obj, key, minimums):
    issues = []
    for field, spec in minimums.items():
        for legacy_id, value in zip(df[key], df[field]):
            if float(value) < spec["min"]:
                issues.append(_issue(obj, legacy_id, spec["reason"], field, value))
    return issues


def check_non_product(df, obj, key, spec):
    """Postage, bank charges, test codes... are not products -> NON_PRODUCT (out of scope)."""
    code_field = spec.get("field", "MATNR")
    patterns = [re.compile(p) for p in spec["patterns"]]
    issues = []
    for legacy_id, code in zip(df[key], df[code_field]):
        if any(p.search(str(code).upper()) for p in patterns):
            issues.append(_issue(obj, legacy_id, spec["reason"], code_field, code))
    return issues


def check_obsolete(df, obj, key, spec):
    """Deletion flag set, or no activity since the cutoff date -> OBSOLETE (not migrated)."""
    issues = []
    flag_field = spec.get("deletion_flag_field")
    date_field = spec["last_activity_field"]
    cutoff = spec["cutoff_date"]
    for _, row in df.iterrows():
        if flag_field and row[flag_field] == "X":
            issues.append(_issue(obj, row[key], "OBSOLETE", flag_field, "X"))
        elif row[date_field] is not None and str(row[date_field]) < cutoff:
            # ISO dates (YYYY-MM-DD) compare correctly as text
            issues.append(_issue(obj, row[key], "OBSOLETE", date_field, row[date_field]))
    return issues


def validate(df: pd.DataFrame, obj: str, rules: dict) -> pd.DataFrame:
    """Run every rule configured for the object; return the quarantine list."""
    r = rules[obj]
    key = "LEGACY_ID"   # legacy number exactly as extracted (added by cleanse)
    issues = []
    issues += check_mandatory(df, obj, key, r.get("mandatory", []))
    issues += check_formats(df, obj, key, r.get("formats", {}))
    if "address" in r:
        issues += check_address(df, obj, key, r["address"])
    issues += check_max_length(df, obj, key, r.get("max_length", {}))
    issues += check_allowed_values(df, obj, key, r.get("allowed_values", {}))
    issues += check_min_value(df, obj, key, r.get("min_value", {}))
    if "non_product_codes" in r:
        issues += check_non_product(df, obj, key, r["non_product_codes"])
    if "obsolete" in r:
        issues += check_obsolete(df, obj, key, r["obsolete"])
    return pd.DataFrame(issues, columns=QUARANTINE_COLUMNS)
