"""Honest findings on the real data (written to metrics.json -> real_data_findings).

1. Address standardisation: how many cities matched the geolocation reference
   exactly, after fuzzy correction, after removing extra text, or not at all.
2. Duplicate detection WITHOUT the cross-reference id: the location-only matcher
   (src/dedup.location_match_pairs) is compared with the ground truth
   UNIQUE_ID (Olist customer_unique_id). Pair-level precision and recall.
   This shows why we merge on UNIQUE_ID and not on location: without a name,
   e-mail or tax number, many different people share a zip prefix and city.
"""

from itertools import combinations

import pandas as pd

from src.dedup import location_match_pairs


def city_match_stats(clean: pd.DataFrame) -> dict:
    counts = clean["CITY_MATCH"].value_counts().to_dict()
    total = len(clean)
    return {method: {"records": int(counts.get(method, 0)),
                     "pct": round(100 * counts.get(method, 0) / total, 2) if total else 0.0}
            for method in ("exact", "fuzzy", "cleaned", "none")}


def truth_pairs(clean: pd.DataFrame, key: str = "UNIQUE_ID") -> set[tuple]:
    """All pairs of legacy ids that really are the same customer."""
    pairs = set()
    for _, group in clean.groupby(key):
        pairs |= {tuple(sorted(p)) for p in combinations(group["LEGACY_ID"], 2)}
    return pairs


def location_matcher_quality(clean: pd.DataFrame, spec: dict) -> dict:
    """Precision / recall of the location-only matcher against UNIQUE_ID."""
    usable = clean[clean["CITY_STD"].notna()]
    truth = truth_pairs(usable)
    found = location_match_pairs(usable, spec)
    hits = len(truth & found)
    return {
        "records_compared": len(usable),
        "true_duplicate_pairs": len(truth),
        "pairs_proposed": len(found),
        "correct_pairs": hits,
        "precision_pct": round(100 * hits / len(found), 2) if found else None,
        "recall_pct": round(100 * hits / len(truth), 2) if truth else None,
    }


def evaluate_findings(clean: dict, rules: dict) -> dict:
    """clean: object -> cleansed DataFrame (before validation)."""
    customers = clean["customer"]
    return {
        "city_standardisation": {obj: city_match_stats(clean[obj]) for obj in ("customer", "vendor")},
        "customer_duplicates": {
            "customer_id_rows": len(customers),
            "unique_customers": int(customers["UNIQUE_ID"].nunique()),
            "duplicate_rows": int(len(customers) - customers["UNIQUE_ID"].nunique()),
        },
        "location_only_matcher_vs_unique_id": location_matcher_quality(
            customers, rules["customer"]["location_matcher"]),
    }
