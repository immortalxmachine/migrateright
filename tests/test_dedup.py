"""Fuzzy matching, clustering and survivorship."""

import pandas as pd

from src.cleanse import cleanse
from src.dedup import UnionFind, deduplicate, golden_record, match_key, pick_survivor
from src.extract import load_legacy
from tests.conftest import FIXTURES

SUFFIXES = ["ltd", "limited", "gmbh", "and", "the", "sarl", "incorporated"]


def test_match_key_removes_suffixes_and_punctuation():
    assert match_key("The Acme & Sons Ltd.", SUFFIXES) == "acme sons"
    assert match_key("Acme G.m.b.H.", SUFFIXES) == "acme"
    assert match_key("Acme Gifts Limite", SUFFIXES) == "acme gifts"      # name cut at 35 chars
    assert match_key("Hawthorn Decor S.A.R.L.", SUFFIXES) == "hawthorn decor"


def test_union_find_groups_transitively():
    uf = UnionFind(["A", "B", "C", "D"])
    uf.union("A", "B")
    uf.union("B", "C")
    assert uf.find("A") == uf.find("C") != uf.find("D")


def test_survivor_is_most_complete_then_newest():
    group = pd.DataFrame([
        {"LEGACY_ID": "1", "NAME1": "Acme", "TELF1": None, "ERDAT": "2020-01-01"},
        {"LEGACY_ID": "2", "NAME1": "Acme", "TELF1": "+44", "ERDAT": "2010-01-01"},
        {"LEGACY_ID": "3", "NAME1": "Acme", "TELF1": "+44", "ERDAT": "2015-01-01"},
    ])
    assert pick_survivor(group, ["completeness", "ERDAT"]) == "3"


def test_golden_record_fills_gaps_from_duplicates():
    group = pd.DataFrame([
        {"LEGACY_ID": "1", "NAME1": "Acme", "EMAIL": None},
        {"LEGACY_ID": "2", "NAME1": "ACME", "EMAIL": "a@acme.example"},
    ])
    golden = golden_record(group, "1")
    assert golden["NAME1"] == "Acme" and golden["EMAIL"] == "a@acme.example"


def test_customer_duplicates_merged(rules, mapping):
    clean = cleanse(load_legacy("customer", FIXTURES), "customer", rules, mapping)
    _, merges = deduplicate(clean, "customer", rules)
    assert len(merges) == 1
    assert merges.iloc[0]["survivor_id"] == "0000000001"     # the more complete record wins
    assert merges.iloc[0]["merged_id"] == "0000000002"


def test_different_companies_not_merged(rules):
    base = {"LAND1": "GB", "ORT01": "London", "EMAIL": None, "TELF1": None, "ERDAT": "2020-01-01"}
    df = pd.DataFrame([
        {"LEGACY_ID": "1", "NAME1": "Pinecrest Lighting Supplies Ltd", "PSTLZ": "EJ9 5NX", **base},
        {"LEGACY_ID": "2", "NAME1": "Pinecrest Living Supplies Ltd", "PSTLZ": "TN9 9FN", **base},
    ]).astype(object)
    df = df.where(df.notna(), None)
    _, merges = deduplicate(df, "customer", rules)
    assert merges.empty      # similar names but only the city matches -> not enough evidence


def test_material_case_variants_merged(rules, mapping):
    clean = cleanse(load_legacy("material", FIXTURES), "material", rules, mapping)
    _, merges = deduplicate(clean, "material", rules)
    assert list(merges["merged_id"]) == ["85123a"]
    assert list(merges["survivor_id"]) == ["85123A"]          # more sales history wins
