"""Cleansing step: normalise legacy values BEFORE validation.

Cleansing only fixes things that are safe to fix automatically:
  * trim / collapse whitespace, blank strings -> missing
  * value maps from config/mapping.yaml (country 'UK' -> 'GB', UoM 'ST' -> 'PC')
  * standard formats: e-mail lower case, postcode upper case, phone -> E.164
Anything that cannot be fixed safely is left as-is so validation can quarantine it.
"""

import re

import pandas as pd


def clean_text(value):
    """'  Acme   Ltd ' -> 'Acme Ltd'; '' or whitespace -> None."""
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
    # Already a valid target code typed in lower case ('gb' -> 'GB')
    if upper in set(lookup.values()):
        return upper
    return value


def normalise_postcode(value, country):
    """Upper case and standard spacing for GB/NL/IE codes ('sw1a1aa' -> 'SW1A 1AA')."""
    if value is None:
        return None
    code = str(value).upper().strip()
    compact = code.replace(" ", "")
    if country == "GB" and 5 <= len(compact) <= 7:
        return f"{compact[:-3]} {compact[-3:]}"
    if country == "NL" and len(compact) == 6:
        return f"{compact[:4]} {compact[4:]}"
    if country == "IE" and len(compact) == 7:
        return f"{compact[:3]} {compact[3:]}"
    return code


def normalise_phone(value, country, country_codes: dict):
    """Convert legacy phone notations to E.164 ('020 7946 0123' -> '+442079460123').

    Only separators (space, dash, dot, brackets) are removed. If letters or
    other characters remain, the original is returned so validation flags it.
    """
    if value is None:
        return None
    raw = str(value).strip()
    compact = re.sub(r"[\s\-\.\(\)]", "", raw)
    if not re.fullmatch(r"\+?\d+", compact):
        return raw                                  # 'N/A', 'TBC', 'ext. 204' -> invalid
    if compact.startswith("+"):
        return compact
    if compact.startswith("00"):
        return "+" + compact[2:]
    cc = country_codes.get(country)
    if cc is None:
        return raw                                  # unknown country: cannot convert
    return "+" + cc + compact.lstrip("0")


def cleanse(df: pd.DataFrame, obj: str, rules: dict, mapping: dict) -> pd.DataFrame:
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

    # 2. value maps (country, unit of measure, ...)
    for field, map_name in mapping["cleanse_value_maps"].get(obj, {}).items():
        vmap = mapping["value_maps"][map_name]
        out[field] = out[field].map(lambda v, m=vmap: apply_value_map(v, m))

    # 3. object-specific standard formats
    if obj in ("customer", "vendor"):
        # names keep their original case; e-mails are case-insensitive
        out["EMAIL"] = out["EMAIL"].map(lambda v: v.lower() if isinstance(v, str) else None)
        out["PSTLZ"] = [normalise_postcode(p, c) for p, c in zip(out["PSTLZ"], out["LAND1"])]
        codes = rules["phone_country_codes"]
        out["TELF1"] = [normalise_phone(p, c, codes) for p, c in zip(out["TELF1"], out["LAND1"])]
    if obj == "material":
        out["MATNR_LEGACY"] = out["LEGACY_ID"]          # becomes MARA-BISMT (old number)
        # S/4 material numbers are upper case
        out["MATNR"] = out["MATNR"].map(lambda v: v.upper() if isinstance(v, str) else None)
        out["STPRS"] = pd.to_numeric(out["STPRS"]).fillna(0.0).astype(float)
        out["TXN_COUNT"] = pd.to_numeric(out["TXN_COUNT"]).fillna(0).astype(int)
    # pandas may store "missing" as NaN; the rest of the pipeline expects None
    out = out.astype(object)
    return out.where(out.notna(), None)
