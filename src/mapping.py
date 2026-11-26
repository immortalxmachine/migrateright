"""Mapping step: cleansed legacy records -> S/4HANA-shaped target tables.

Driven by config/mapping.yaml. Customers and vendors both become Business
Partners (BUT000 + BUT020 + ADRC) with a role in BUT100 and a link from the
legacy number (CVI_CUST_LINK / CVI_VEND_LINK). Target fields that the source
does not have ({not_in_source: ...}) are left empty - never invented.
"""

import pandas as pd

FIRST_PARTNER = 1000000000      # internal BP number range (10 digits)
FIRST_ADDRESS = 2000000000      # ADRC address numbers


def map_value(column_spec: dict, row: dict, value_maps: dict, generated: dict):
    """Resolve one target column for one record according to its mapping spec."""
    if "constant" in column_spec:
        return column_spec["constant"]
    if "generated" in column_spec:
        return generated[column_spec["generated"]]
    if "not_in_source" in column_spec:
        return None                                     # documented gap, left empty
    value = row.get(column_spec["source"])
    if "value_map" in column_spec and value is not None:
        return value_maps[column_spec["value_map"]].get(value, value)
    return value


def build_rows(row: dict, table_spec: dict, value_maps: dict, generated: dict) -> dict:
    return {col: map_value(spec, row, value_maps, generated) for col, spec in table_spec.items()}


def unmapped_fields(mapping: dict) -> list[dict]:
    """List of target fields left empty because the source does not have them (for the README)."""
    rows = []
    for obj, spec in mapping["objects"].items():
        for table, columns in spec["tables"].items():
            for col, col_spec in columns.items():
                if "not_in_source" in col_spec:
                    rows.append({"object": obj, "table": table, "field": col, "note": col_spec["not_in_source"]})
    return rows


def map_business_partners(customers: pd.DataFrame, vendors: pd.DataFrame, mapping: dict) -> dict:
    """Build BUT000, BUT020, ADRC, BUT100 and the CVI link tables."""
    value_maps = mapping["value_maps"]
    tables = {name: [] for name in ["BUT000", "BUT020", "ADRC", "BUT100", "CVI_CUST_LINK", "CVI_VEND_LINK"]}
    next_partner, next_address = FIRST_PARTNER, FIRST_ADDRESS
    for obj, df in (("customer", customers), ("vendor", vendors)):
        spec = mapping["objects"][obj]
        for row in df.to_dict("records"):
            generated = {"partner": f"{next_partner:010d}", "address": f"{next_address:010d}"}
            next_partner += 1
            next_address += 1
            for table in ("BUT000", "BUT020", "ADRC"):
                tables[table].append(build_rows(row, spec["tables"][table], value_maps, generated))
            tables["BUT100"].append({"PARTNER": generated["partner"], "RLTYP": spec["role"]})
            tables[spec["link_table"]].append({"PARTNER": generated["partner"],
                                               spec["link_field"]: row["LEGACY_ID"]})
    return {name: pd.DataFrame(rows) for name, rows in tables.items()}


def map_materials(materials: pd.DataFrame, mapping: dict) -> dict:
    """Build MARA, MAKT and MBEW from the cleansed material survivors."""
    value_maps = mapping["value_maps"]
    spec = mapping["objects"]["material"]["tables"]
    rows = materials.to_dict("records")
    return {table: pd.DataFrame([build_rows(r, spec[table], value_maps, {}) for r in rows])
            for table in ("MARA", "MAKT", "MBEW")}
