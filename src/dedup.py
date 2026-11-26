"""Duplicate detection and survivorship.

Business partners (customers / vendors):
  1. Blocking   - only compare records in the same block (country), which keeps
                  the number of comparisons small.
  2. Matching   - rapidfuzz token_sort_ratio on a "match key" of the name
                  (lower case, no punctuation, no legal suffixes such as Ltd/GmbH).
                  A pair is a duplicate when the name score >= threshold AND at
                  least one support field (city, postcode, e-mail, phone) is equal.
  3. Clustering - pairs are joined into groups with union-find (A~B, B~C -> {A,B,C}).
  4. Survivorship - per group the most complete record survives (tie: newest
                  ERDAT, then lowest legacy number); its empty fields are filled
                  from the other members -> one "golden record".
Materials: exact match on the upper-cased material number; the code with the
most sales history survives.

Merged records are never deleted: they are written to the merge log with the
survivor's id and the match score, so reconciliation can account for them.
"""

import re

import pandas as pd
from rapidfuzz import fuzz

MERGE_COLUMNS = ["object", "survivor_id", "merged_id", "score", "match_reason"]


def match_key(name, legal_suffixes) -> str:
    """'The Acme & Sons Ltd.' -> 'acme sons'"""
    if name is None:
        return ""
    text = str(name).lower().replace(".", "")            # 'G.m.b.H.' -> 'gmbh'
    words = re.sub(r"[^a-z0-9 ]", " ", text).split()     # '&', ',' ... -> space
    stop = set(legal_suffixes)
    # Legacy names are cut at 35 characters, so 'Limited' may arrive as 'Limite':
    # drop a last word that is the start of a legal suffix.
    if words and len(words[-1]) >= 3 and any(s.startswith(words[-1]) for s in stop):
        words = words[:-1]
    return " ".join(w for w in words if w not in stop)


def name_score(a: str, b: str) -> float:
    """0-100 similarity that ignores word order ('Home Acme' == 'Acme Home')."""
    return fuzz.token_sort_ratio(a, b)


class UnionFind:
    """Tiny union-find (disjoint set) to turn duplicate pairs into groups."""

    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]   # path halving
            x = self.parent[x]
        return x

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def find_duplicate_pairs(df: pd.DataFrame, spec: dict, legal_suffixes) -> list[tuple]:
    """Return (id_a, id_b, score, reason) for every matching pair inside each block."""
    keys = df[spec["name_field"]].map(lambda n: match_key(n, legal_suffixes))
    work = df.assign(_key=keys)
    pairs = []
    for _, block in work.groupby(spec["block_on"], dropna=False):
        records = block.to_dict("records")
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                a, b = records[i], records[j]
                score = name_score(a["_key"], b["_key"])
                if score < spec["name_threshold"]:
                    continue
                support = [f for f in spec["support_fields"]
                           if a[f] is not None and a[f] == b[f]]
                if len(support) >= spec["min_support_matches"]:
                    reason = f"name {score:.0f} + {', '.join(support)}"
                    pairs.append((a["LEGACY_ID"], b["LEGACY_ID"], round(score, 1), reason))
    return pairs


def completeness(row: pd.Series) -> int:
    """Number of filled fields - the main survivorship criterion."""
    return int(row.notna().sum())


def pick_survivor(group: pd.DataFrame, rule: list[str]) -> str:
    """Survivorship: most complete, then newest ERDAT, then lowest legacy id."""
    ranked = group.assign(_complete=group.apply(completeness, axis=1))
    sort_cols, ascending = [], []
    for criterion in rule:
        if criterion == "completeness":
            sort_cols.append("_complete")
            ascending.append(False)
        else:                               # a date / number field: higher wins
            sort_cols.append(criterion)
            ascending.append(False)
    sort_cols.append("LEGACY_ID")
    ascending.append(True)
    return ranked.sort_values(sort_cols, ascending=ascending).iloc[0]["LEGACY_ID"]


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


def deduplicate_partners(df, obj, spec, legal_suffixes):
    """Return (golden records, merge log) for customers or vendors."""
    pairs = find_duplicate_pairs(df, spec, legal_suffixes)
    uf = UnionFind(df["LEGACY_ID"])
    best = {}
    for a, b, score, reason in pairs:
        uf.union(a, b)
        best[a] = best[b] = (score, reason)

    groups = df.assign(_group=df["LEGACY_ID"].map(uf.find)).groupby("_group")
    survivors, merges = [], []
    for _, group in groups:
        group = group.drop(columns="_group")
        if len(group) == 1:
            survivors.append(group.iloc[0])
            continue
        survivor_id = pick_survivor(group, spec["survivorship"])
        survivors.append(golden_record(group, survivor_id))
        for merged_id in group["LEGACY_ID"]:
            if merged_id != survivor_id:
                score, reason = best[merged_id]
                merges.append({"object": obj, "survivor_id": survivor_id,
                               "merged_id": merged_id, "score": score,
                               "match_reason": reason})
    result = pd.DataFrame(survivors).reset_index(drop=True)
    return result, pd.DataFrame(merges, columns=MERGE_COLUMNS)


def deduplicate_materials(df, obj, spec):
    """Exact match on the normalised material number (85123A == 85123a)."""
    key = spec["exact_key"]
    order = spec["survivorship"]                          # e.g. ["TXN_COUNT"]
    ranked = df.sort_values(order + ["LEGACY_ID"], ascending=[False] * len(order) + [True])
    survivors = ranked.drop_duplicates(subset=key, keep="first")
    survivor_of = dict(zip(survivors[key], survivors["LEGACY_ID"]))   # code -> survivor id
    merges = []
    for legacy_id, code in zip(ranked["LEGACY_ID"], ranked[key]):
        survivor_id = survivor_of[code]
        if legacy_id != survivor_id:
            merges.append({"object": obj, "survivor_id": survivor_id, "merged_id": legacy_id,
                           "score": 100.0, "match_reason": f"same {key} after upper-casing"})
    return survivors.sort_values(key).reset_index(drop=True), pd.DataFrame(merges, columns=MERGE_COLUMNS)


def deduplicate(df: pd.DataFrame, obj: str, rules: dict):
    spec = rules[obj]["dedup"]
    if obj == "material":
        return deduplicate_materials(df, obj, spec)
    return deduplicate_partners(df, obj, spec, rules["legal_suffixes"])
