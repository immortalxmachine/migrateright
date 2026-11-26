"""One test per validation rule in config/rules.yaml."""

import pandas as pd

from src import rules as r
from src.address import GeoReference
from src.cleanse import cleanse
from src.extract import load_geo_reference, load_legacy
from tests.conftest import FIXTURES

GEO = GeoReference(load_geo_reference(FIXTURES))


def frame(**cols):
    """Small DataFrame with None for missing values and a LEGACY_ID column ID0, ID1..."""
    df = pd.DataFrame(cols).astype(object)
    df = df.where(df.notna(), None)
    df.insert(0, "LEGACY_ID", [f"ID{i}" for i in range(len(df))])
    return df


def hits(issues):
    return sorted((i["legacy_id"], i["rule"]) for i in issues)


def test_mandatory():
    df = frame(ORT01=["campinas", None])
    assert hits(r.check_mandatory(df, "customer", "LEGACY_ID", ["ORT01"])) == [("ID1", "MISSING_MANDATORY")]


def test_postal_code_format(rules):
    df = frame(PSTLZ=["01001", "1234X", None])
    issues = r.check_formats(df, "customer", "LEGACY_ID", rules["customer"]["formats"])
    assert hits(issues) == [("ID1", "INVALID_POSTAL_CODE")]        # empty is MISSING_MANDATORY's job


def test_allowed_state(rules):
    df = frame(REGIO=["SP", "XX"])
    spec = {"REGIO": rules["customer"]["allowed_values"]["REGIO"]}
    assert hits(r.check_allowed_values(df, "customer", "LEGACY_ID", spec)) == [("ID1", "INVALID_STATE")]
    assert len(rules["customer"]["allowed_values"]["REGIO"]["values"]) == 27   # 26 states + DF


def test_address_rules():
    df = frame(PSTLZ=["01001", "99999", "88301", "01001"], ORT01=["sao paulo", "x", "itajai", "sp"],
               REGIO=["SP", "SP", "SP", "SP"],
               GEO_REGIO=["SP", None, "SC", "SP"], CITY_MATCH=["exact", "none", "exact", "none"])
    spec = {"zip_field": "PSTLZ", "city_field": "ORT01", "state_field": "REGIO"}
    assert hits(r.check_address(df, "vendor", "LEGACY_ID", spec)) == [
        ("ID1", "ZIP_NOT_FOUND"), ("ID2", "ZIP_STATE_MISMATCH"), ("ID3", "CITY_ZIP_MISMATCH")]


def test_max_length():
    df = frame(ORT01=["campinas", "X" * 41])
    assert hits(r.check_max_length(df, "customer", "LEGACY_ID", {"ORT01": 40})) == [("ID1", "FIELD_TOO_LONG")]


def test_min_price(rules):
    df = frame(STPRS=[2.95, 0.0])
    issues = r.check_min_value(df, "material", "LEGACY_ID", rules["material"]["min_value"])
    assert hits(issues) == [("ID1", "MISSING_PRICE")]


def test_non_product_codes(rules):
    df = frame(MATNR=["85123A", "POST", "BANK CHARGES", "TEST001"])
    issues = r.check_non_product(df, "material", "LEGACY_ID", rules["material"]["non_product_codes"])
    assert hits(issues) == [("ID1", "NON_PRODUCT"), ("ID2", "NON_PRODUCT"), ("ID3", "NON_PRODUCT")]


def test_material_description_rule(rules):
    df = frame(MAKTX=["WHITE HANGING HEART", "damaged", "??", "SET OF 4 TINS"])
    issues = r.check_formats(df, "material", "LEGACY_ID", rules["material"]["formats"])
    assert hits(issues) == [("ID1", "INVALID_DESCRIPTION"), ("ID2", "INVALID_DESCRIPTION")]


def test_obsolete_by_last_activity(rules):
    df = frame(LAST_ACTIVITY=["2018-01-01", "2016-06-30"])
    issues = r.check_obsolete(df, "customer", "LEGACY_ID", rules["customer"]["obsolete"])
    assert hits(issues) == [("ID1", "OBSOLETE")]


def test_validate_vendor_fixture(rules, mapping):
    clean = cleanse(load_legacy("vendor", FIXTURES), "vendor", rules, mapping, GEO)
    q = r.validate(clean, "vendor", rules)
    assert list(q.columns) == r.QUARANTINE_COLUMNS
    by_id = q.groupby("legacy_id")["rule"].apply(set).to_dict()
    assert by_id == {
        "s0000000000000000000000000000002": {"ZIP_STATE_MISMATCH"},        # zip of SC typed as SP
        "s0000000000000000000000000000003": {"CITY_ZIP_MISMATCH"},         # city typed as 'sp'
        "s0000000000000000000000000000006": {"OBSOLETE"},
        "s0000000000000000000000000000007": {"INVALID_STATE", "ZIP_STATE_MISMATCH"},
    }
