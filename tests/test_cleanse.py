"""Cleansing: whitespace, value maps, postcode and phone normalisation."""

from src.cleanse import apply_value_map, clean_text, cleanse, normalise_phone, normalise_postcode
from src.extract import load_legacy
from tests.conftest import FIXTURES

CODES = {"GB": "44", "DE": "49", "US": "1"}


def test_clean_text_collapses_whitespace_and_blanks():
    assert clean_text("  Acme   Gifts  Ltd ") == "Acme Gifts Ltd"
    assert clean_text("   ") is None
    assert clean_text(None) is None


def test_country_value_map_is_case_insensitive(mapping):
    countries = mapping["value_maps"]["country"]
    assert apply_value_map("UK", countries) == "GB"
    assert apply_value_map("germany", countries) == "DE"
    assert apply_value_map("gb", countries) == "GB"              # valid code typed in lower case
    assert apply_value_map("Atlantis", countries) == "Atlantis"  # unknown -> left for validation


def test_uom_value_map(mapping):
    assert apply_value_map("ST", mapping["value_maps"]["uom"]) == "PC"
    assert apply_value_map("PAK", mapping["value_maps"]["uom"]) == "PAC"


def test_postcode_normalisation():
    assert normalise_postcode("sw1a1aa", "GB") == "SW1A 1AA"
    assert normalise_postcode("1234ab", "NL") == "1234 AB"
    assert normalise_postcode("20095", "DE") == "20095"


def test_phone_to_e164():
    assert normalise_phone("020 7946 0123", "GB", CODES) == "+442079460123"
    assert normalise_phone("0049 30 1234 5678", "DE", CODES) == "+493012345678"
    assert normalise_phone("+1 (617) 555-0100", "US", CODES) == "+16175550100"
    assert normalise_phone("N/A", "GB", CODES) == "N/A"          # left unchanged -> fails validation


def test_cleanse_fixture_customers(rules, mapping):
    clean = cleanse(load_legacy("customer", FIXTURES), "customer", rules, mapping)
    row = clean.set_index("LEGACY_ID").loc["0000000002"]
    assert row["LAND1"] == "GB"               # 'UK' fixed by the value map
    assert row["PSTLZ"] == "SW1A 1AA"         # 'sw1a1aa' normalised
    assert row["TELF1"] is None               # missing stays None (not NaN)
