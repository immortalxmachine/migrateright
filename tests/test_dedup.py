"""Exact-key dedup with survivorship, and the location-only matcher used for evaluation."""

import pandas as pd

from src.address import GeoReference
from src.cleanse import cleanse
from src.dedup import deduplicate, golden_record, location_match_pairs, pick_survivor
from src.evaluate import location_matcher_quality, truth_pairs
from src.extract import load_geo_reference, load_legacy
from tests.conftest import FIXTURES

GEO = GeoReference(load_geo_reference(FIXTURES))


def test_survivor_is_newest_then_lowest_id():
    group = pd.DataFrame([
        {"LEGACY_ID": "b", "LAST_ACTIVITY": "2018-01-01"},
        {"LEGACY_ID": "a", "LAST_ACTIVITY": "2018-01-01"},
        {"LEGACY_ID": "c", "LAST_ACTIVITY": "2017-01-01"},
    ])
    assert pick_survivor(group, ["LAST_ACTIVITY"]) == "a"


def test_golden_record_fills_gaps_from_duplicates():
    group = pd.DataFrame([{"LEGACY_ID": "1", "ORT01": "campinas", "ERDAT": None},
                          {"LEGACY_ID": "2", "ORT01": "campinas", "ERDAT": "2017-01-01"}])
    assert golden_record(group, "1")["ERDAT"] == "2017-01-01"


def test_customers_merged_on_unique_id(rules, mapping):
    clean = cleanse(load_legacy("customer", FIXTURES), "customer", rules, mapping, GEO)
    _, merges = deduplicate(clean, "customer", rules)
    assert len(merges) == 1
    assert merges.iloc[0]["survivor_id"] == "c0000000000000000000000000000002"   # newest order wins
    assert merges.iloc[0]["merged_id"] == "c0000000000000000000000000000001"


def test_vendors_not_deduplicated(rules, mapping):
    clean = cleanse(load_legacy("vendor", FIXTURES), "vendor", rules, mapping, GEO)
    survivors, merges = deduplicate(clean, "vendor", rules)
    assert merges.empty and len(survivors) == len(clean)


def test_material_case_variants_merged(rules, mapping):
    clean = cleanse(load_legacy("material", FIXTURES), "material", rules, mapping)
    _, merges = deduplicate(clean, "material", rules)
    assert list(merges["merged_id"]) == ["85123a"]
    assert list(merges["survivor_id"]) == ["85123A"]          # more sales history wins


def test_location_matcher_has_false_positives(rules, mapping):
    """Location alone cannot tell people apart: c1, c2 and c3 share zip + city, only c1/c2 are one person."""
    clean = cleanse(load_legacy("customer", FIXTURES), "customer", rules, mapping, GEO)
    spec = rules["customer"]["location_matcher"]
    found = location_match_pairs(clean, spec)
    ids = [f"c{i:031d}" for i in (1, 2, 3)]
    assert (ids[0], ids[1]) in found and (ids[0], ids[2]) in found
    assert truth_pairs(clean) == {(ids[0], ids[1])}
    quality = location_matcher_quality(clean, spec)
    assert quality["recall_pct"] == 100.0 and quality["precision_pct"] < 50
