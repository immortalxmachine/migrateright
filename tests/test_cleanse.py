"""Cleansing and address standardisation."""

from src.address import GeoReference, pretty_city
from src.cleanse import apply_value_map, clean_text, cleanse, normalise_zip_prefix
from src.extract import city_key, load_geo_reference, load_legacy
from tests.conftest import FIXTURES

GEO = GeoReference(load_geo_reference(FIXTURES))


def test_clean_text_collapses_whitespace_and_blanks():
    assert clean_text("  sao   paulo ") == "sao paulo"
    assert clean_text("   ") is None
    assert clean_text(None) is None


def test_uom_value_map(mapping):
    assert apply_value_map("ST", mapping["value_maps"]["uom"]) == "PC"
    assert apply_value_map("pak", mapping["value_maps"]["uom"]) == "PAC"
    assert apply_value_map("XYZ", mapping["value_maps"]["uom"]) == "XYZ"   # unknown -> validation


def test_zip_prefix_gets_leading_zero_back():
    assert normalise_zip_prefix("1001") == "01001"
    assert normalise_zip_prefix("01001") == "01001"
    assert normalise_zip_prefix("abc") == "abc"            # left for the format rule


def test_city_key_and_pretty_city():
    assert city_key("São  Paulo") == "sao paulo"
    assert city_key("sao paulo / sp") == "sao paulo sp"
    assert pretty_city("são joão del rei") == "São João del Rei"


def test_city_matching_methods():
    assert GEO.match_city("01001", "sao paulo", 85) == ("São Paulo", "exact", 100.0)
    assert GEO.match_city("01001", "sao pauo", 85)[:2] == ("São Paulo", "fuzzy")
    assert GEO.match_city("80240", "curitiba / pr", 85)[:2] == ("Curitiba", "cleaned")
    assert GEO.match_city("01001", "sp", 85)[:2] == (None, "none")
    assert GEO.match_city("99999", "campinas", 85)[:2] == (None, "none")     # unknown zip


def test_cleanse_fixture_customers(rules, mapping):
    clean = cleanse(load_legacy("customer", FIXTURES), "customer", rules, mapping, GEO)
    row = clean.set_index("LEGACY_ID").loc["c0000000000000000000000000000003"]
    assert row["PSTLZ"] == "01001"            # leading zero restored
    assert row["REGIO"] == "SP"               # 'sp' upper-cased
    assert row["CITY_STD"] == "São Paulo"     # reference spelling
    assert row["GEO_REGIO"] == "SP"
