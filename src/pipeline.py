"""MigrateRight end-to-end run:  extract -> profile -> cleanse -> validate -> dedup
-> map -> load -> reconcile -> reports + metrics.json

Usage:  python -m src.pipeline            (SQLite by default)
        MIGRATERIGHT_DB_URL=postgresql+psycopg2://... python -m src.pipeline
"""

import json
import time
from datetime import UTC, datetime

import pandas as pd

from src import profile as profiling  # our src/profile.py, not the stdlib module
from src.cleanse import cleanse
from src.config import METRICS_PATH, OBJECTS, REPORTS_DIR, get_engine, load_mapping, load_rules
from src.dedup import deduplicate
from src.evaluate import evaluate_detection
from src.extract import load_legacy
from src.load import load_all, run_ddl, stage_source
from src.mapping import map_business_partners, map_materials
from src.reconcile import reason_breakdown, reconcile_object, summarise
from src.report_excel import build_workbook
from src.rules import validate


def log(step: str, message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {step:<10} {message}", flush=True)


def run(engine=None, legacy_folder=None, reports_dir=REPORTS_DIR, metrics_path=METRICS_PATH,
        evaluate: bool = True) -> dict:
    started = time.perf_counter()
    rules, mapping = load_rules(), load_mapping()
    engine = engine or get_engine()
    backend = engine.dialect.name
    log("START", f"MigrateRight run - target database: {backend}")

    # 1. EXTRACT ------------------------------------------------------------
    raw = {obj: load_legacy(obj, legacy_folder) for obj in OBJECTS}
    for obj in OBJECTS:
        log("EXTRACT", f"{obj:<9} {len(raw[obj]):>6,} legacy records")

    # 2. PROFILE (raw data, before any change) ------------------------------
    profiles = {obj: profiling.profile_dataframe(raw[obj], obj, rules) for obj in OBJECTS}
    profiling.write_html_report(profiles, raw, reports_dir / "profiling_report.html")
    log("PROFILE", f"{sum(len(p) for p in profiles.values())} fields profiled -> "
                   "reports/profiling_report.html")

    # 3-5. CLEANSE -> VALIDATE -> DEDUP --------------------------------------
    survivors, quarantine, merges, counts = {}, [], [], {}
    for obj in OBJECTS:
        clean = cleanse(raw[obj], obj, rules, mapping)
        issues = validate(clean, obj, rules)
        bad_ids = set(issues["legacy_id"])
        valid = clean[~clean["LEGACY_ID"].isin(bad_ids)]
        golden, merged = deduplicate(valid, obj, rules)
        survivors[obj] = golden
        quarantine.append(issues)
        merges.append(merged)
        counts[obj] = {"records_in": len(raw[obj]), "quarantined": len(bad_ids),
                       "merged": len(merged), "loaded": len(golden)}
        log("CLEANSE", f"{obj:<9} {len(bad_ids):>6,} quarantined ({len(issues):,} rule failures), "
                       f"{len(merged):,} duplicates merged, {len(golden):,} survivors")
    quarantine = pd.concat(quarantine, ignore_index=True)
    merges = pd.concat(merges, ignore_index=True)

    # 6. MAP to S/4HANA structures -------------------------------------------
    bp_tables, shared = map_business_partners(survivors["customer"], survivors["vendor"],
                                              mapping, rules["legal_suffixes"])
    product_tables = map_materials(survivors["material"], mapping)
    counts["vendor"]["shared_bp"] = len(shared)
    log("MAP", f"{len(bp_tables['BUT000']):,} business partners "
               f"({len(shared)} customer+vendor shared), {len(product_tables['MARA']):,} products")

    # 7. LOAD ----------------------------------------------------------------
    run_ddl(engine)
    for obj in OBJECTS:
        stage_source(engine, obj, raw[obj])
    written = load_all(engine, {**bp_tables, **product_tables}, quarantine, merges, shared)
    log("LOAD", ", ".join(f"{t}={n:,}" for t, n in written.items() if t.startswith("tgt_")))

    # 8. RECONCILE -----------------------------------------------------------
    checks, samples = [], []
    shared_ids = set(shared["vendor_id"])
    for obj in OBJECTS:
        obj_checks, sample = reconcile_object(engine, obj, counts[obj]["records_in"],
                                              survivors[obj],
                                              shared_ids if obj == "vendor" else set(), mapping)
        checks += obj_checks
        samples.append(sample)
    checks = pd.DataFrame(checks)
    samples = pd.concat(samples, ignore_index=True)
    summary = summarise(checks, counts)
    reasons = reason_breakdown(quarantine, {o: c["records_in"] for o, c in counts.items()})
    for table, df in (("mig_recon_checks", checks), ("mig_recon_summary", summary),
                      ("mig_recon_sample", samples), ("mig_reason_summary", reasons),
                      ("mig_profile", pd.concat(profiles.values(), ignore_index=True))):
        df.to_sql(table, engine, if_exists="replace", index=False)
    passed = int((checks["status"] == "PASS").sum())
    log("RECON", f"{passed}/{len(checks)} reconciliation checks passed")

    # 9. REPORTS + METRICS ---------------------------------------------------
    build_workbook(reports_dir / "reconciliation_report.xlsx", summary, reasons, checks, samples,
                   quarantine, merges, backend)
    log("REPORT", "reports/reconciliation_report.xlsx")

    metrics = build_metrics(counts, reasons, summary, checks, backend, started)
    if evaluate and legacy_folder is None:
        metrics["detection_vs_injected_issues"] = evaluate_detection(quarantine, merges, shared, survivors)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    log("METRICS", f"metrics.json written - overall status {metrics['overall_status']}")
    for obj, c in counts.items():
        log("RESULT", f"{obj:<9} in={c['records_in']:,} loaded={c['loaded']:,} "
                      f"quarantined={c['quarantined']:,} merged={c['merged']:,}")
    log("DONE", f"finished in {time.perf_counter() - started:.1f}s")
    return metrics


def build_metrics(counts, reasons, summary, checks, backend, started) -> dict:
    total_in = sum(c["records_in"] for c in counts.values())
    total_q = sum(c["quarantined"] for c in counts.values())
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "database": backend,
        "runtime_seconds": round(time.perf_counter() - started, 1),
        "totals": {
            "records_in": total_in,
            "records_loaded": sum(c["loaded"] for c in counts.values()),
            "records_quarantined": total_q,
            "duplicates_merged": sum(c["merged"] for c in counts.values()),
            "quarantined_pct": round(100 * total_q / total_in, 2),
            "business_partners_created": int(summary.loc[summary["object"] != "material", "loaded"].sum()
                                             - counts["vendor"].get("shared_bp", 0)),
            "shared_customer_vendor_bps": counts["vendor"].get("shared_bp", 0),
        },
        "objects": {
            row["object"]: {
                "records_in": int(row["records_in"]), "records_loaded": int(row["loaded"]),
                "records_quarantined": int(row["quarantined"]),
                "duplicates_merged": int(row["duplicates_merged"]),
                "rejected_pct": float(row["rejected_pct"]),
                "rejected_pct_by_reason": {
                    r["rule"]: float(r["pct_of_records_in"])
                    for _, r in reasons[reasons["object"] == row["object"]].iterrows()},
                "rejected_records_by_reason": {
                    r["rule"]: int(r["records"])
                    for _, r in reasons[reasons["object"] == row["object"]].iterrows()},
                "recon_checks_passed": f"{row['checks_passed']}/{row['checks_total']}",
            } for _, row in summary.iterrows()},
        "reconciliation_checks_passed": int((checks["status"] == "PASS").sum()),
        "reconciliation_checks_total": len(checks),
        "overall_status": "PASS" if (checks["status"] == "PASS").all() else "FAIL",
    }


if __name__ == "__main__":
    run()
