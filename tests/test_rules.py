"""One test per validation rule in config/rules.yaml."""

import pandas as pd

from src import rules as r
from src.cleanse import cleanse
from src.extract import load_legacy
from tests.conftest import FIXTURES


def frame(**cols):
    """Small DataFrame with None for missing values and a LEGACY_ID column ID0, ID1..."""
    df = pd.DataFrame(cols).astype(object)
    df = df.where(df.notna(), None)
    df.insert(0, "LEGACY_ID", [f"ID{i}" for i in range(len(df))])
    return df


def hits(issues):
    return sorted((i["legacy_id"], i["rule"]) for i in issues)


def test_mandatory():
    df = frame(NAME1=["Acme", None])
    assert hits(r.check_mandatory(df, "customer", "LEGACY_ID", ["NAME1"])) == [("ID1", "MISSING_MANDATORY")]


def test_email_format(rules):
    df = frame(EMAIL=["info@acme.example", "bad.email", None])
    spec = {"EMAIL": rules["customer"]["formats"]["EMAIL"]}
    # an empty optional e-mail is fine; only the malformed one fails
    assert hits(r.check_formats(df, "customer", "LEGACY_ID", spec)) == [("ID1", "INVALID_EMAIL")]


def test_phone_format(rules):
    df = frame(TELF1=["+442079460123", "+4412345", "N/A"])
    spec = {"TELF1": rules["customer"]["formats"]["TELF1"]}
    assert hits(r.check_formats(df, "customer", "LEGACY_ID", spec)) == [
        ("ID1", "INVALID_PHONE"), ("ID2", "INVALID_PHONE")]


def test_postal_code_per_country(rules):
    df = frame(PSTLZ=["SW1A 1AA", "20095", "1234", "ABC"], LAND1=["GB", "DE", "DE", "GB"])
    issues = r.check_postal_codes(df, "customer", "LEGACY_ID", rules["customer"]["postal_code"],
                                  rules["postal_formats"])
    assert hits(issues) == [("ID2", "INVALID_POSTAL_CODE"), ("ID3", "INVALID_POSTAL_CODE")]


def test_allowed_country(rules):
    df = frame(LAND1=["GB", "Atlantis"])
    spec = {"LAND1": rules["customer"]["allowed_values"]["LAND1"]}
    assert hits(r.check_allowed_values(df, "customer", "LEGACY_ID", spec)) == [("ID1", "INVALID_COUNTRY")]


def test_max_length():
    df = frame(NAME1=["Short", "X" * 41])
    assert hits(r.check_max_length(df, "customer", "LEGACY_ID", {"NAME1": 40})) == [("ID1", "FIELD_TOO_LONG")]


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


def test_obsolete_flag_and_date(rules):
    df = frame(LOEVM=[None, "X", None], LAST_ACTIVITY=["2024-01-01", "2024-01-01", "2015-06-30"])
    issues = r.check_obsolete(df, "customer", "LEGACY_ID", rules["customer"]["obsolete"])
    assert hits(issues) == [("ID1", "OBSOLETE"), ("ID2", "OBSOLETE")]


def test_validate_on_fixture(rules, mapping):
    clean = cleanse(load_legacy("customer", FIXTURES), "customer", rules, mapping)
    q = r.validate(clean, "customer", rules)
    assert list(q.columns) == r.QUARANTINE_COLUMNS
    # 3 = missing name, 4 = bad e-mail, 6 = deletion flag, 7 = DE postcode '1234'
    assert set(q["legacy_id"]) == {"0000000003", "0000000004", "0000000006", "0000000007"}
