"""Extract step: build / read the legacy ECC-style extracts (all REAL public data).

Case study: a Brazilian retailer's customer and vendor master (Olist) and a UK
retailer's product master (Online Retail II) are migrated to S/4HANA.

  Customers (KNA1-like) <- Olist olist_customers + order dates   (Kaggle olistbr/brazilian-ecommerce,
  Vendors   (LFA1-like) <- Olist olist_sellers   + sale dates      CC BY-NC-SA 4.0)
  Address reference     <- Olist olist_geolocation (zip prefix -> city / state)
  Materials (MARA-like) <- Online Retail II invoice lines (UCI id 502 / Kaggle, CC BY 4.0)

The raw downloads are gitignored. This script writes small, deterministic
extracts to data/legacy/ that are committed, so CI never needs a download or
Kaggle credentials.

Usage:  python -m src.extract [materials|olist|all]
"""

import hashlib
import re
import sys
import unicodedata

import pandas as pd

from src.config import LEGACY_DIR, ROOT

RAW_XLSX = ROOT / "data" / "raw" / "online_retail_ii" / "online_retail_II.xlsx"
RAW_OLIST = ROOT / "data" / "raw" / "olist"
MATERIAL_CSV = LEGACY_DIR / "mara_legacy.csv"
CUSTOMER_CSV = LEGACY_DIR / "kna1_legacy.csv"
VENDOR_CSV = LEGACY_DIR / "lfa1_legacy.csv"
GEO_CSV = LEGACY_DIR / "geo_reference.csv"

LEGACY_FILES = {"customer": CUSTOMER_CSV, "vendor": VENDOR_CSV, "material": MATERIAL_CSV}

# Keep 1 in N unique customers (all their customer_id rows, so duplicate groups stay whole).
CUSTOMER_SAMPLE_EVERY = 10


def city_key(value) -> str:
    """'São  Paulo' -> 'sao paulo' (no accents, lower case, letters/digits/spaces only)."""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text)).strip()


def in_sample(unique_id: str, every: int = CUSTOMER_SAMPLE_EVERY) -> bool:
    """Deterministic sample: the same customers are picked on every machine."""
    return int(hashlib.md5(unique_id.encode()).hexdigest(), 16) % every == 0


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


def build_olist_extracts(raw=RAW_OLIST):
    """Customers, sellers and the address reference from the raw Olist CSVs."""
    read = lambda name: pd.read_csv(raw / f"olist_{name}_dataset.csv", dtype=str)  # noqa: E731
    customers, sellers, orders = read("customers"), read("sellers"), read("orders")
    items, geo = read("order_items"), read("geolocation")
    orders["ORDER_DATE"] = orders["order_purchase_timestamp"].str[:10]

    # --- customers (KNA1-like): each customer_id is one order's customer record
    cust = customers[customers["customer_unique_id"].map(in_sample)]
    cust = cust.merge(orders[["customer_id", "ORDER_DATE", "order_status"]], on="customer_id", how="left")
    kna1 = pd.DataFrame({
        "KUNNR": cust["customer_id"],                 # legacy customer number (32-char hash in Olist)
        "UNIQUE_ID": cust["customer_unique_id"],      # legacy cross-reference to the real person
        "PSTLZ": cust["customer_zip_code_prefix"],    # first 5 digits of the CEP postcode
        "ORT01": cust["customer_city"],
        "REGIO": cust["customer_state"],              # UF (state) code
        "ERDAT": cust["ORDER_DATE"],                  # first (only) order of this customer_id
        "LAST_ACTIVITY": cust["ORDER_DATE"],
        "ORDER_STATUS": cust["order_status"],
    }).sort_values("KUNNR")

    # --- vendors (LFA1-like): first / last sale date per seller
    sales = items.merge(orders[["order_id", "ORDER_DATE"]], on="order_id")
    dates = sales.groupby("seller_id")["ORDER_DATE"].agg(["min", "max", "size"])
    sell = sellers.join(dates, on="seller_id")
    lfa1 = pd.DataFrame({
        "LIFNR": sell["seller_id"], "PSTLZ": sell["seller_zip_code_prefix"], "ORT01": sell["seller_city"],
        "REGIO": sell["seller_state"], "ERDAT": sell["min"], "LAST_ACTIVITY": sell["max"],
        "ITEM_COUNT": sell["size"].fillna(0).astype(int),
    }).sort_values("LIFNR")

    # --- address reference: one row per zip prefix + city (+ the best spelling of the city)
    geo["CITY_KEY"] = geo["geolocation_city"].map(city_key)
    geo["HAS_ACCENT"] = geo["geolocation_city"].map(lambda c: city_key(c) != str(c).lower().strip())
    spelled = (geo.groupby(["geolocation_zip_code_prefix", "CITY_KEY", "geolocation_state",
                            "geolocation_city", "HAS_ACCENT"]).size().reset_index(name="POINTS"))
    # prefer an accented spelling ("são paulo"), then the most frequent one
    spelled = spelled.sort_values(["HAS_ACCENT", "POINTS"], ascending=False)
    best = spelled.drop_duplicates(["geolocation_zip_code_prefix", "CITY_KEY", "geolocation_state"])
    points = spelled.groupby(["geolocation_zip_code_prefix", "CITY_KEY", "geolocation_state"])["POINTS"].sum()
    ref = best.drop(columns="POINTS").join(points, on=["geolocation_zip_code_prefix", "CITY_KEY",
                                                      "geolocation_state"])
    geo_ref = pd.DataFrame({"ZIP_PREFIX": ref["geolocation_zip_code_prefix"], "CITY_KEY": ref["CITY_KEY"],
                            "CITY": ref["geolocation_city"].str.strip(), "REGIO": ref["geolocation_state"],
                            "POINTS": ref["POINTS"]}).sort_values(["ZIP_PREFIX", "CITY_KEY"])
    return kna1, lfa1, geo_ref


def load_legacy(obj: str, folder=None) -> pd.DataFrame:
    """Read one legacy extract as text (keeps leading zeros, e.g. KUNNR 0000100001)."""
    path = LEGACY_FILES[obj] if folder is None else folder / LEGACY_FILES[obj].name
    df = pd.read_csv(path, dtype=str, keep_default_na=False).astype(object)
    # Empty strings mean "not filled" in the legacy extract -> None
    return df.where(df != "", None)


def load_geo_reference(folder=None) -> pd.DataFrame:
    """Zip prefix -> city/state reference used for address validation."""
    path = GEO_CSV if folder is None else folder / GEO_CSV.name
    return pd.read_csv(path, dtype=str, keep_default_na=False)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    LEGACY_DIR.mkdir(parents=True, exist_ok=True)
    if what in ("materials", "all"):
        extract = build_material_extract()
        extract.to_csv(MATERIAL_CSV, index=False)
        print(f"Wrote {len(extract):,} legacy materials to {MATERIAL_CSV}")
    if what in ("olist", "all"):
        kna1, lfa1, geo_ref = build_olist_extracts()
        kna1.to_csv(CUSTOMER_CSV, index=False)
        lfa1.to_csv(VENDOR_CSV, index=False)
        geo_ref.to_csv(GEO_CSV, index=False)
        print(f"Wrote {len(kna1):,} customers (1 in {CUSTOMER_SAMPLE_EVERY} unique customers), "
              f"{len(lfa1):,} vendors, {len(geo_ref):,} address reference rows")
