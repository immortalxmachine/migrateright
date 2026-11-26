"""Profiling step: measure the quality of the RAW legacy data before touching it.

Per field: completeness, uniqueness, format validity (using the regexes in
config/rules.yaml), the most common "shapes" (e.g. postcode 'AA9 9AA') and the
most common values. Output: reports/profiling_report.html (+ a DataFrame that
the pipeline stores in table mig_profile for the dashboard).

NOTE: this file is called profile.py as requested. Python also has a standard
module called `profile`, so always import it as a package module:
    from src import profile as profiling
"""

import html
import re
from datetime import datetime

import pandas as pd


def shape(value) -> str:
    """'SW1A 1AA' -> 'AA9A 9AA', '0049 30 123' -> '9999 99 999'."""
    s = re.sub(r"[A-Za-z]", "A", str(value))
    return re.sub(r"[0-9]", "9", s)


def field_validity(series: pd.Series, regex: str | None):
    """% of filled values that match the field's regex (None if no rule exists)."""
    filled = series.dropna()
    if regex is None or filled.empty:
        return None
    pattern = re.compile(regex)
    return round(100 * filled.map(lambda v: bool(pattern.fullmatch(str(v)))).mean(), 1)


def profile_dataframe(df: pd.DataFrame, obj: str, rules: dict) -> pd.DataFrame:
    """One row per field with the profiling measures."""
    r = rules[obj]
    mandatory = set(r.get("mandatory", []))
    formats = {f: spec["regex"] for f, spec in r.get("formats", {}).items()}
    allowed = {f: spec["values"] for f, spec in r.get("allowed_values", {}).items()}
    rows = []
    total = len(df)
    for col in df.columns:
        series = df[col].map(lambda v: None if v is None or str(v).strip() == "" else v)
        filled = series.dropna()
        distinct = filled.nunique()
        validity = field_validity(series, formats.get(col))
        if col in allowed and not filled.empty:
            # % of values already using an allowed target code (before value mapping)
            validity = round(100 * filled.isin(allowed[col]).mean(), 1)
        shapes = filled.map(shape).value_counts().head(3)
        values = filled.value_counts().head(5)
        lengths = filled.astype(str).str.len()
        rows.append({
            "object": obj,
            "field": col,
            "mandatory": "Y" if col in mandatory else "",
            "filled_pct": round(100 * len(filled) / total, 1) if total else 0.0,
            "distinct": int(distinct),
            "uniqueness_pct": round(100 * distinct / len(filled), 1) if len(filled) else 0.0,
            "validity_pct": validity,
            "min_len": int(lengths.min()) if not lengths.empty else 0,
            "max_len": int(lengths.max()) if not lengths.empty else 0,
            "top_shapes": "; ".join(f"{s} ({n})" for s, n in shapes.items()),
            "top_values": "; ".join(f"{v} ({n})" for v, n in values.items()),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- HTML report
CSS = """
body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1f2933;background:#fff}
h1{margin:0 0 4px} .sub{color:#52606d;margin-bottom:20px}
h2{margin-top:28px;border-bottom:2px solid #0a6ed1;padding-bottom:4px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0}
.card{background:#f0f4f8;border-radius:6px;padding:8px 14px;min-width:120px}
.card b{display:block;font-size:20px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th{background:#0a6ed1;color:#fff;text-align:left;padding:6px}
td{border-bottom:1px solid #e4e7eb;padding:5px 6px;vertical-align:top}
.bar{background:#e4e7eb;width:90px;height:10px;border-radius:5px;display:inline-block}
.bar i{display:block;height:10px;border-radius:5px}
.good{background:#2f9e44}.warn{background:#f08c00}.bad{background:#e03131}
.small{color:#52606d;font-size:11.5px}
"""


def _bar(pct):
    if pct is None or pd.isna(pct):
        return "<span class='small'>no rule</span>"
    cls = "good" if pct >= 98 else "warn" if pct >= 90 else "bad"
    return f"<span class='bar'><i class='{cls}' style='width:{pct}%'></i></span> {pct}%"


def write_html_report(profiles: dict, raw: dict, path) -> None:
    """profiles: object -> profile DataFrame; raw: object -> raw DataFrame."""
    parts = [f"<html><head><meta charset='utf-8'><title>MigrateRight - Data Profiling</title>"
             f"<style>{CSS}</style></head><body>",
             "<h1>Legacy data profiling report</h1>",
             f"<div class='sub'>MigrateRight &middot; SAP ECC extract before cleansing &middot; "
             f"generated {datetime.now():%Y-%m-%d %H:%M}</div>"]
    for obj, prof in profiles.items():
        df = raw[obj]
        mandatory = prof[prof["mandatory"] == "Y"]
        complete_rows = df[list(mandatory["field"])].notna().all(axis=1).mean() * 100
        label = {"customer": "Customers (KNA1, SYNTHETIC)", "vendor": "Vendors (LFA1, SYNTHETIC)",
                 "material": "Materials (MARA/MAKT, real Online Retail II stock codes)"}[obj]
        parts.append(f"<h2>{label}</h2><div class='cards'>"
                     f"<div class='card'>Records<b>{len(df):,}</b></div>"
                     f"<div class='card'>Fields<b>{len(df.columns)}</b></div>"
                     f"<div class='card'>Rows with all mandatory fields<b>{complete_rows:.1f}%</b></div>"
                     "</div>")
        parts.append("<table><tr><th>Field</th><th>Mand.</th><th>Completeness</th><th>Distinct</th>"
                     "<th>Unique %</th><th>Validity</th><th>Len</th><th>Top shapes</th>"
                     "<th>Top values</th></tr>")
        for _, p in prof.iterrows():
            parts.append(
                f"<tr><td><b>{p.field}</b></td><td>{p.mandatory}</td><td>{_bar(p.filled_pct)}</td>"
                f"<td>{p.distinct:,}</td><td>{p.uniqueness_pct}</td><td>{_bar(p.validity_pct)}</td>"
                f"<td>{p.min_len}-{p.max_len}</td><td class='small'>{html.escape(p.top_shapes)}</td>"
                f"<td class='small'>{html.escape(p.top_values)}</td></tr>")
        parts.append("</table>")
    parts.append("<p class='small'>Validity = share of filled values matching the rule in "
                 "config/rules.yaml (format regex or allowed values), measured on raw legacy "
                 "values before cleansing/value mapping.</p></body></html>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")
