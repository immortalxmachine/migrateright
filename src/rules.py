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


def check_postal_codes(df, obj, key, spec, postal_formats):
    """Postcode must match the format of its (already mapped) country."""
    issues = []
    field, country_field = spec["field"], spec["country_field"]
    for legacy_id, code, country in zip(df[key], df[field], df[country_field]):
        pattern = postal_formats.get(country)
        # Missing code / unknown country are reported by other rules already
        if code is None or pattern is None:
            continue
        if not re.fullmatch(pattern, str(code)):
            issues.append(_issue(obj, legacy_id, spec["reason"], field, code))
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


def check_non_product(df, obj, key, spec, code_field="MATNR"):
    """Postage, bank charges, test codes... are not products -> NON_PRODUCT (out of scope)."""
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
    if "postal_code" in r:
        issues += check_postal_codes(df, obj, key, r["postal_code"], rules["postal_formats"])
    issues += check_max_length(df, obj, key, r.get("max_length", {}))
    issues += check_allowed_values(df, obj, key, r.get("allowed_values", {}))
    issues += check_min_value(df, obj, key, r.get("min_value", {}))
    if "non_product_codes" in r:
        issues += check_non_product(df, obj, key, r["non_product_codes"])
    if "obsolete" in r:
        issues += check_obsolete(df, obj, key, r["obsolete"])
    return pd.DataFrame(issues, columns=QUARANTINE_COLUMNS)
