"""Legacy -> S/4HANA Business Partner and product mapping."""

import pandas as pd

from src.mapping import map_business_partners, map_materials, unmapped_fields


def partner(legacy_id, city="São Paulo", zip_prefix="01001", state="SP"):
    return {"LEGACY_ID": legacy_id, "KUNNR": legacy_id, "LIFNR": legacy_id, "PSTLZ": zip_prefix,
            "ORT01": "sao paulo", "CITY_STD": city, "REGIO": state, "ERDAT": "2017-05-01"}


def test_customer_maps_to_person_bp_with_address_and_role(mapping):
    customers = pd.DataFrame([partner("c1")])
    tables = map_business_partners(customers, customers.iloc[0:0], mapping)
    but000 = tables["BUT000"].iloc[0]
    assert but000["BU_TYPE"] == "1" and but000["BU_GROUP"] == "BPCU"
    assert but000["NAME_FIRST"] is None and but000["NAME_LAST"] is None      # not in source: left empty
    assert but000["CRDAT"] == "2017-05-01"
    adrc = tables["ADRC"].iloc[0]
    assert adrc["CITY1"] == "São Paulo"          # standardised city, not the raw text
    assert adrc["POST_CODE1"] == "01001" and adrc["REGION"] == "SP" and adrc["COUNTRY"] == "BR"
    assert adrc["TEL_NUMBER"] is None and adrc["SMTP_ADDR"] is None and adrc["STREET"] is None
    assert tables["BUT020"].iloc[0]["ADDRNUMBER"] == adrc["ADDRNUMBER"]
    assert list(tables["BUT100"]["RLTYP"]) == ["FLCU01"]
    assert tables["CVI_CUST_LINK"].iloc[0]["KUNNR"] == "c1"


def test_vendor_is_organisation_with_vendor_role(mapping):
    vendors = pd.DataFrame([partner("s1"), partner("s2", "Campinas", "13023")])
    tables = map_business_partners(vendors.iloc[0:0], vendors, mapping)
    assert list(tables["BUT000"]["BU_TYPE"]) == ["2", "2"]
    assert list(tables["BUT100"]["RLTYP"]) == ["FLVN01", "FLVN01"]
    assert tables["BUT000"]["PARTNER"].is_unique


def test_unmapped_fields_are_documented(mapping):
    gaps = {(g["object"], g["table"], g["field"]) for g in unmapped_fields(mapping)}
    assert ("customer", "ADRC", "SMTP_ADDR") in gaps and ("vendor", "BUT000", "NAME_ORG1") in gaps


def test_material_maps_to_mara_makt_mbew(mapping):
    materials = pd.DataFrame([{"MATNR": "85123A", "MATNR_LEGACY": "85123a", "MAKTX": "WHITE HEART",
                               "MTART": "HAWA", "MEINS": "PC", "STPRS": 2.95, "ERSDA": "2009-12-01"}])
    t = map_materials(materials, mapping)
    assert t["MARA"].iloc[0].to_dict() == {"MATNR": "85123A", "MTART": "HAWA", "MEINS": "PC",
                                          "BISMT": "85123a", "ERSDA": "2009-12-01"}
    assert t["MAKT"].iloc[0]["SPRAS"] == "E"
    assert t["MBEW"].iloc[0]["STPRS"] == 2.95
    assert t["MBEW"].iloc[0]["BWKEY"] == "UK01"
