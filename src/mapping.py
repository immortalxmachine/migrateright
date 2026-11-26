"""Mapping step: cleansed legacy records -> S/4HANA-shaped target tables.

Driven by config/mapping.yaml. The interesting part is Customer-Vendor
Integration (CVI): in S/4HANA the Business Partner is the single entry point,
so a company that is both a customer (KNA1) and a vendor (LFA1) must become
ONE partner with two roles (FLCU01 + FLVN01), not two partners.
"""

import pandas as pd

from src.dedup import match_key

FIRST_PARTNER = 1000000000      # internal BP number range (10 digits)
FIRST_ADDRESS = 2000000000      # ADRC address numbers


def map_value(column_spec: dict, row: dict, value_maps: dict, generated: dict):
    """Resolve one target column for one record according to its mapping spec."""
    if "constant" in column_spec:
        return column_spec["constant"]
    if "generated" in column_spec:
        return generated[column_spec["generated"]]
    value = row.get(column_spec["source"])
    if "value_map" in column_spec and value is not None:
        return value_maps[column_spec["value_map"]].get(value, value)
    return value


def build_rows(row: dict, table_spec: dict, value_maps: dict, generated: dict) -> dict:
    return {col: map_value(spec, row, value_maps, generated) for col, spec in table_spec.items()}


def shared_key(row: dict, legal_suffixes) -> tuple:
    """Same company = same cleaned name + country + postcode."""
    return (match_key(row["NAME1"], legal_suffixes), row["LAND1"], row["PSTLZ"])


def map_business_partners(customers: pd.DataFrame, vendors: pd.DataFrame,
                          mapping: dict, legal_suffixes) -> tuple[dict, pd.DataFrame]:
    """Build BUT000, BUT020, ADRC, BUT100 and the CVI link tables.

    Returns (tables, shared) where shared lists vendors that re-used a customer's BP.
    """
    value_maps = mapping["value_maps"]
    tables = {name: [] for name in ["BUT000", "BUT020", "ADRC", "BUT100",
                                    "CVI_CUST_LINK", "CVI_VEND_LINK"]}
    next_partner, next_address = FIRST_PARTNER, FIRST_ADDRESS
    partner_by_company = {}       # shared_key -> partner number
    shared = []

    for obj, df in (("customer", customers), ("vendor", vendors)):
        spec = mapping["objects"][obj]
        for row in df.to_dict("records"):
            company = shared_key(row, legal_suffixes)
            if obj == "vendor" and company in partner_by_company:
                # CVI: vendor is a company we already created as customer -> add a role only
                partner = partner_by_company[company]
                shared.append({"partner": partner, "vendor_id": row["LEGACY_ID"]})
            else:
                partner = f"{next_partner:010d}"
                generated = {"partner": partner, "address": f"{next_address:010d}"}
                next_partner += 1
                next_address += 1
                for table in ("BUT000", "BUT020", "ADRC"):
                    tables[table].append(build_rows(row, spec["tables"][table], value_maps, generated))
                partner_by_company.setdefault(company, partner)
            tables["BUT100"].append({"PARTNER": partner, "RLTYP": spec["role"]})
            tables[spec["link_table"]].append({"PARTNER": partner, spec["link_field"]: row["LEGACY_ID"]})

    frames = {name: pd.DataFrame(rows) for name, rows in tables.items()}
    return frames, pd.DataFrame(shared, columns=["partner", "vendor_id"])


def map_materials(materials: pd.DataFrame, mapping: dict) -> dict:
    """Build MARA, MAKT and MBEW from the cleansed material survivors."""
    value_maps = mapping["value_maps"]
    spec = mapping["objects"]["material"]["tables"]
    rows = materials.to_dict("records")
    return {table: pd.DataFrame([build_rows(r, spec[table], value_maps, {}) for r in rows])
            for table in ("MARA", "MAKT", "MBEW")}
