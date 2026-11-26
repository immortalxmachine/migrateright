"""Legacy -> S/4HANA Business Partner and product mapping."""

import pandas as pd

from src.mapping import map_business_partners, map_materials


def partner(legacy_id, name, country="DE", postcode="20095"):
    return {"LEGACY_ID": legacy_id, "KUNNR": legacy_id, "LIFNR": legacy_id, "NAME1": name,
            "NAME2": None, "STRAS": "Gartenweg 2", "ORT01": "Hamburg", "PSTLZ": postcode,
            "LAND1": country, "TELF1": "+494098765432",
            "EMAIL": "info@x.example", "KTOKD": "Z002", "KTOKK": "Z100", "ERDAT": "2012-06-01"}


def test_customer_maps_to_but000_adrc_and_role(mapping):
    customers = pd.DataFrame([partner("0000000008", "Beta Kitchen GmbH")])
    tables, _ = map_business_partners(customers, customers.iloc[0:0], mapping, ["gmbh"])
    but000 = tables["BUT000"].iloc[0]
    assert but000["BU_TYPE"] == "2"                    # organisation
    assert but000["BU_GROUP"] == "BPCU"                # KTOKD Z002 -> BP grouping
    assert but000["NAME_ORG1"] == "Beta Kitchen GmbH"
    assert but000["BPEXT"] == "0000000008"             # legacy number kept
    adrc = tables["ADRC"].iloc[0]
    assert adrc["COUNTRY"] == "DE" and adrc["POST_CODE1"] == "20095"
    assert tables["BUT020"].iloc[0]["ADDRNUMBER"] == adrc["ADDRNUMBER"]
    assert list(tables["BUT100"]["RLTYP"]) == ["FLCU01"]
    assert tables["CVI_CUST_LINK"].iloc[0]["KUNNR"] == "0000000008"


def test_customer_and_vendor_share_one_business_partner(mapping):
    customers = pd.DataFrame([partner("0000000008", "Beta Kitchen GmbH")])
    vendors = pd.DataFrame([partner("0000000102", "Beta Kitchen G.m.b.H."),
                            partner("0000000101", "Hotel Packaging Ltd", "GB", "BS2 0AA")])
    tables, shared = map_business_partners(customers, vendors, mapping, ["gmbh", "ltd"])
    assert len(tables["BUT000"]) == 2                  # 3 legacy records -> 2 partners
    assert len(shared) == 1
    roles = tables["BUT100"].groupby("PARTNER")["RLTYP"].apply(sorted).tolist()
    assert ["FLCU01", "FLVN01"] in roles               # one BP carries both roles


def test_material_maps_to_mara_makt_mbew(mapping):
    materials = pd.DataFrame([{"MATNR": "85123A", "MATNR_LEGACY": "85123a", "MAKTX": "WHITE HEART",
                               "MTART": "HAWA", "MEINS": "PC", "STPRS": 2.95, "ERSDA": "2009-12-01"}])
    t = map_materials(materials, mapping)
    assert t["MARA"].iloc[0].to_dict() == {"MATNR": "85123A", "MTART": "HAWA", "MEINS": "PC",
                                          "BISMT": "85123a", "ERSDA": "2009-12-01"}
    assert t["MAKT"].iloc[0]["SPRAS"] == "E"
    assert t["MBEW"].iloc[0]["STPRS"] == 2.95
    assert t["MBEW"].iloc[0]["BWKEY"] == "UK01"
