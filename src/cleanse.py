"""Cleansing step: normalise legacy values BEFORE validation.

Cleansing only fixes things that are safe to fix automatically:
  * trim / collapse whitespace, blank strings -> missing
  * value maps from config/mapping.yaml (UoM 'ST' -> 'PC')
  * customers/vendors: zip prefix to 5 digits, state upper case, city matched to
    the geolocation reference (src/address.py) -> CITY_STD
  * materials: material number upper case, numbers as numbers
Anything that cannot be fixed safely is left as-is so validation can quarantine it.
"""

import re

import pandas as pd

from src.address import GeoReference, standardise_addresses


def clean_text(value):
    """'  sao   paulo ' -> 'sao paulo'; '' or whitespace -> None."""
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def apply_value_map(value, value_map: dict):
    """Translate a legacy code via a value map (case-insensitive). Unknown values pass through."""
    if value is None or pd.isna(value):
        return None
    upper = str(value).upper()
    lookup = {str(k).upper(): v for k, v in value_map.items()}
    if upper in lookup:
        return lookup[upper]
    if upper in set(lookup.values()):        # already a valid target code typed in lower case
        return upper
    return value


def normalise_zip_prefix(value):
    """'1151' -> '01151' (a leading zero lost when the zip was stored as a number)."""
    if value is None:
        return None
    text = str(value).strip()
    return text.zfill(5) if text.isdigit() and len(text) < 5 else text


def cleanse(df: pd.DataFrame, obj: str, rules: dict, mapping: dict, geo: GeoReference | None = None) -> pd.DataFrame:
    """Return a cleansed copy of a legacy extract (the input is not modified)."""
    out = df.copy()
    key = rules[obj]["key"]

    # 1. whitespace on every text column
    for col in out.columns:
        out[col] = out[col].map(clean_text)
    out = out.astype(object)
    out = out.where(out.notna(), None)        # pandas may turn None into NaN; we want None

    # LEGACY_ID = the legacy number exactly as extracted; used for traceability
    # (e.g. materials 85123A and 85123a are two legacy records with one target number)
    out.insert(0, "LEGACY_ID", out[key])

    # 2. value maps (unit of measure, ...)
    for field, map_name in mapping.get("cleanse_value_maps", {}).get(obj, {}).items():
        vmap = mapping["value_maps"][map_name]
        out[field] = out[field].map(lambda v, m=vmap: apply_value_map(v, m))

    # 3. object-specific standard formats
    if "address" in rules[obj]:
        spec = rules[obj]["address"]
        out[spec["zip_field"]] = out[spec["zip_field"]].map(normalise_zip_prefix)
        out[spec["state_field"]] = out[spec["state_field"]].map(lambda v: v.upper() if isinstance(v, str) else None)
        if geo is not None:
            out = standardise_addresses(out, geo, spec)
    if obj == "material":
        out["MATNR_LEGACY"] = out["LEGACY_ID"]          # becomes MARA-BISMT (old number)
        # S/4 material numbers are upper case
        out["MATNR"] = out["MATNR"].map(lambda v: v.upper() if isinstance(v, str) else None)
        out["STPRS"] = pd.to_numeric(out["STPRS"]).fillna(0.0).astype(float)
        out["TXN_COUNT"] = pd.to_numeric(out["TXN_COUNT"]).fillna(0).astype(int)
    out = out.astype(object)
    return out.where(out.notna(), None)
