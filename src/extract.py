"""Extract step: build / read the legacy ECC extracts.

Materials come from REAL data: the Online Retail II invoice lines (UCI / Kaggle,
CC BY 4.0) are condensed into one row per stock code, shaped like an ECC
material master (MARA/MAKT/MBEW fields). Customers and vendors are SYNTHETIC
(see src/generate_synthetic.py).

Usage:  python -m src.extract     (needs the raw xlsx from src/download.py)
"""

import re

import pandas as pd

from src.config import LEGACY_DIR, ROOT

RAW_XLSX = ROOT / "data" / "raw" / "online_retail_ii" / "online_retail_II.xlsx"
MATERIAL_CSV = LEGACY_DIR / "mara_legacy.csv"
CUSTOMER_CSV = LEGACY_DIR / "kna1_legacy.csv"
VENDOR_CSV = LEGACY_DIR / "lfa1_legacy.csv"

LEGACY_FILES = {"customer": CUSTOMER_CSV, "vendor": VENDOR_CSV, "material": MATERIAL_CSV}


def legacy_uom(description: str) -> str:
    """Derive an ECC-style unit key from the description text.

    The source data has no unit of measure, so we use a documented heuristic:
    'SET OF 4 ...' -> SET, 'PACK OF 12 ...' -> PAK, everything else -> ST (piece).
    """
    text = str(description).upper()
    if re.search(r"\bSET\b", text):
        return "SET"
    if re.search(r"\bPACK\b", text):
        return "PAK"
    return "ST"


def legacy_material_type(stock_code: str) -> str:
    """Product codes start with digits (trading goods), the rest are services/fees."""
    return "HAWA" if re.match(r"^\d", str(stock_code)) else "DIEN"


def build_material_extract(xlsx_path=RAW_XLSX) -> pd.DataFrame:
    """Condense ~1M invoice lines into one legacy material record per stock code."""
    sheets = pd.read_excel(xlsx_path, sheet_name=None, dtype={"StockCode": str})
    lines = pd.concat(sheets.values(), ignore_index=True)
    lines["StockCode"] = lines["StockCode"].astype(str).str.strip()

    def most_common_description(series: pd.Series) -> str:
        values = series.dropna()
        return values.mode().iloc[0] if not values.empty else None

    grouped = lines.groupby("StockCode", sort=True)
    materials = pd.DataFrame({
        "MATNR": grouped.size().index,
        # Most frequent description is the "master" text; others are variants
        "MAKTX": grouped["Description"].agg(most_common_description).values,
        "DESC_VARIANTS": grouped["Description"].nunique().values,
        # Median of positive unit prices = legacy standard price (0 if never sold > 0)
        "STPRS": grouped["Price"].agg(lambda p: p[p > 0].median()).fillna(0).round(2).values,
        "TXN_COUNT": grouped.size().values,
        "ERSDA": grouped["InvoiceDate"].min().dt.strftime("%Y-%m-%d").values,
        "LAST_SOLD": grouped["InvoiceDate"].max().dt.strftime("%Y-%m-%d").values,
    })
    materials["MEINS"] = materials["MAKTX"].apply(legacy_uom)
    materials["MTART"] = materials["MATNR"].apply(legacy_material_type)
    columns = ["MATNR", "MAKTX", "MTART", "MEINS", "STPRS", "ERSDA", "LAST_SOLD",
               "TXN_COUNT", "DESC_VARIANTS"]
    return materials[columns]


def load_legacy(obj: str, folder=None) -> pd.DataFrame:
    """Read one legacy extract as text (keeps leading zeros, e.g. KUNNR 0000100001)."""
    path = LEGACY_FILES[obj] if folder is None else folder / LEGACY_FILES[obj].name
    df = pd.read_csv(path, dtype=str, keep_default_na=False).astype(object)
    # Empty strings mean "not filled" in the legacy extract -> None
    return df.where(df != "", None)


if __name__ == "__main__":
    LEGACY_DIR.mkdir(parents=True, exist_ok=True)
    extract = build_material_extract()
    extract.to_csv(MATERIAL_CSV, index=False)
    print(f"Wrote {len(extract):,} legacy materials to {MATERIAL_CSV}")
