"""Duplicate handling: exact-key merge with survivorship, plus a fuzzy location matcher.

Merge (configured per object in config/rules.yaml -> dedup):
  method: exact  group records on a key and keep one survivor per group
                 customers: UNIQUE_ID (Olist customer_unique_id - one real person,
                            many customer_id rows, one per order)
                 materials: upper-cased material number (85123A == 85123a)
  method: none   no duplicate handling (vendors: seller_id is already unique)
Survivorship: sort the group by the configured fields (highest/newest first),
ties -> lowest legacy id; the survivor's empty fields are filled from the
other members (golden record). Merged ids go to the merge log, never deleted.

Location matcher (customers, evaluation only):
  Could we have found the same duplicates WITHOUT the cross-reference id?
  Block on zip prefix, rapidfuzz ratio on the standardised city, same state.
  src/evaluate.py measures its precision/recall against UNIQUE_ID.
"""

import pandas as pd
from rapidfuzz import fuzz

MERGE_COLUMNS = ["object", "survivor_id", "merged_id", "score", "match_reason"]


def pick_survivor(group: pd.DataFrame, survivorship: list[str]) -> str:
    """Highest value of the survivorship fields wins (newest date / most sales), then lowest id."""
    ranked = group.sort_values(survivorship + ["LEGACY_ID"],
                               ascending=[False] * len(survivorship) + [True])
    return ranked.iloc[0]["LEGACY_ID"]


def golden_record(group: pd.DataFrame, survivor_id: str) -> pd.Series:
    """Survivor's values, with its empty fields filled from the other duplicates."""
    survivor = group[group["LEGACY_ID"] == survivor_id].iloc[0].copy()
    others = group[group["LEGACY_ID"] != survivor_id]
    for col in group.columns:
        if survivor[col] is None or pd.isna(survivor[col]):
            filled = others[col].dropna()
            if not filled.empty:
                survivor[col] = filled.iloc[0]
    return survivor


def deduplicate_exact(df: pd.DataFrame, obj: str, spec: dict):
    """Group on spec['key']; return (survivors, merge log)."""
    key, survivorship = spec["key"], spec["survivorship"]
    survivors, merges = [], []
    for _, group in df.groupby(key, sort=True):
        if len(group) == 1:
            survivors.append(group.iloc[0])
            continue
        survivor_id = pick_survivor(group, survivorship)
        survivors.append(golden_record(group, survivor_id))
        for merged_id in sorted(group["LEGACY_ID"]):
            if merged_id != survivor_id:
                merges.append({"object": obj, "survivor_id": survivor_id, "merged_id": merged_id,
                               "score": 100.0, "match_reason": f"same {key}"})
    result = pd.DataFrame(survivors).reset_index(drop=True) if survivors else df.iloc[0:0]
    return result, pd.DataFrame(merges, columns=MERGE_COLUMNS)


def deduplicate(df: pd.DataFrame, obj: str, rules: dict):
    spec = rules[obj]["dedup"]
    if spec["method"] == "exact" and not df.empty:
        return deduplicate_exact(df, obj, spec)
    return df.reset_index(drop=True), pd.DataFrame(columns=MERGE_COLUMNS)


def location_match_pairs(df: pd.DataFrame, spec: dict, state_field: str = "REGIO") -> set[tuple]:
    """Candidate duplicate pairs using location only (zip block + fuzzy city + same state)."""
    pairs = set()
    for _, block in df.groupby(spec["block_on"]):
        records = block[["LEGACY_ID", spec["city_field"], state_field]].to_dict("records")
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                a, b = records[i], records[j]
                if a[state_field] != b[state_field] or a[spec["city_field"]] is None:
                    continue
                if fuzz.ratio(str(a[spec["city_field"]]), str(b[spec["city_field"]] or "")) >= spec["city_threshold"]:
                    pairs.add(tuple(sorted((a["LEGACY_ID"], b["LEGACY_ID"]))))
    return pairs
