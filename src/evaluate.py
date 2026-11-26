"""Measure how many of the deliberately injected issues the pipeline caught.

The synthetic generator logs every issue it injects (data/legacy/injected_issues.csv).
Comparing that ground truth with the quarantine table / merge log gives a
detection rate per issue type, plus precision and recall for duplicate matching.
"""

import pandas as pd

from src.config import LEGACY_DIR

# injected issue -> the quarantine rule that should catch it
EXPECTED_RULE = {"MISSING_MANDATORY": "MISSING_MANDATORY", "INVALID_POSTAL_CODE": "INVALID_POSTAL_CODE",
                 "INVALID_EMAIL": "INVALID_EMAIL", "INVALID_PHONE": "INVALID_PHONE",
                 "INVALID_COUNTRY": "INVALID_COUNTRY", "OBSOLETE": "OBSOLETE"}


def evaluate_detection(quarantine: pd.DataFrame, merges: pd.DataFrame, shared: pd.DataFrame,
                       survivors: dict, issues_path=LEGACY_DIR / "injected_issues.csv") -> dict:
    issues = pd.read_csv(issues_path, dtype=str)
    caught = set(zip(quarantine["object"], quarantine["legacy_id"], quarantine["rule"]))
    result = {}

    for issue, rule in EXPECTED_RULE.items():
        subset = issues[issues["issue"] == issue]
        hits = sum((o, i, rule) in caught for o, i in zip(subset["object"], subset["legacy_id"]))
        result[issue] = {"injected": len(subset), "detected": hits,
                         "detection_pct": round(100 * hits / len(subset), 1) if len(subset) else None}

    # Country variants ('UK', 'Germany') should be FIXED by the value map and loaded, not rejected
    variants = issues[issues["issue"] == "COUNTRY_VARIANT"]
    loaded = {(o, i) for o in ("customer", "vendor") for i in survivors[o]["LEGACY_ID"]}
    merged = set(zip(merges["object"], merges["merged_id"]))
    fixed = sum(((o, i) in loaded or (o, i) in merged) for o, i in zip(variants["object"], variants["legacy_id"]))
    result["COUNTRY_VARIANT_auto_fixed"] = {"injected": len(variants), "fixed_and_loaded": fixed,
                                            "fixed_pct": round(100 * fixed / len(variants), 1)}

    # Duplicates: a true pair is (duplicate id, original id) from the generator log
    dups = issues[issues["issue"] == "DUPLICATE"]
    true_pairs = {(o, i, d.split()[2]) for o, i, d in zip(dups["object"], dups["legacy_id"], dups["detail"])}
    found_pairs = {(o, m, s) for o, m, s in zip(merges["object"], merges["merged_id"], merges["survivor_id"])}
    found_pairs |= {(o, s, m) for o, m, s in found_pairs}          # order inside a pair does not matter
    partner_merges = merges[merges["object"] != "material"]
    tp = sum(p in found_pairs for p in true_pairs)
    correct = sum((o, m, s) in true_pairs or (o, s, m) in true_pairs
                  for o, m, s in zip(partner_merges["object"], partner_merges["merged_id"],
                                     partner_merges["survivor_id"]))
    result["DUPLICATE"] = {
        "injected_pairs": len(true_pairs), "merges_made": len(partner_merges),
        "recall_pct": round(100 * tp / len(true_pairs), 1) if true_pairs else None,
        "precision_pct": round(100 * correct / len(partner_merges), 1) if len(partner_merges) else None,
    }

    sh = issues[issues["issue"] == "SHARED_BP"]
    detected = len(set(sh["legacy_id"]) & set(shared["vendor_id"]))
    result["SHARED_BP"] = {"injected": len(sh), "detected": detected,
                           "detection_pct": round(100 * detected / len(sh), 1) if len(sh) else None}
    return result
