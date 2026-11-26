"""Generate SYNTHETIC legacy ECC customer (KNA1-like) and vendor (LFA1-like) records.

*** All customer/vendor records are fake. Company names are random word
combinations, e-mail domains use the reserved ".example" TLD. ***

Known data-quality issues are injected on purpose and logged to
data/legacy/injected_issues.csv so the pipeline's detection can be measured:
  DUPLICATE            fuzzy copy of another record (typo, suffix, case, '&'/'and')
  MISSING_MANDATORY    a mandatory field blanked
  INVALID_POSTAL_CODE  postcode that does not fit the country format
  INVALID_EMAIL        malformed e-mail address
  INVALID_PHONE        phone that cannot be turned into E.164
  COUNTRY_VARIANT      'UK', 'Germany', 'DEU'... (fixable by value mapping)
  INVALID_COUNTRY      country that cannot be mapped
  OBSOLETE             deletion flag set or no activity since before 2019
  SHARED_BP            vendor that is the same company as a customer (one BP, two roles)

Usage:  python -m src.generate_synthetic
"""

import random

import pandas as pd

from src.config import LEGACY_DIR

SEED = 42

# --- word lists for fake but realistic-looking company names ---------------
ADJECTIVES = ["Northwind", "Bluebell", "Silverline", "Redwood", "Greenfield", "Ironbridge",
              "Goldcrest", "Brightwater", "Oakridge", "Stonegate", "Westbrook", "Kingsway",
              "Harbourside", "Maplewood", "Clearview", "Riverside", "Highland", "Sunrise",
              "Lakeshore", "Fairway", "Copperleaf", "Ashford", "Pinecrest", "Starling",
              "Thornbury", "Wildrose", "Elmstead", "Foxglove", "Granite", "Hawthorn"]
NOUNS = ["Crafts", "Home", "Gifts", "Kitchen", "Garden", "Living", "Paper", "Candle",
         "Textile", "Ceramics", "Toys", "Decor", "Party", "Vintage", "Lighting", "Stationery",
         "Bakeware", "Florals", "Interiors", "Woodworks"]
TRADES = ["Trading", "Supplies", "Retail", "Wholesale", "Imports", "Distribution",
          "Logistics", "Packaging", "Merchants", "Services"]

# country -> (legal suffix, cities, street names, local phone prefix)
COUNTRIES = {
    "GB": ("Ltd", ["London", "Manchester", "Leeds", "Bristol", "Birmingham"],
           ["High Street", "Station Road", "Church Lane", "Victoria Road"], "0"),
    "DE": ("GmbH", ["Berlin", "Hamburg", "Munich", "Cologne", "Frankfurt"],
           ["Hauptstrasse", "Bahnhofstrasse", "Gartenweg", "Schulstrasse"], "0"),
    "FR": ("SARL", ["Paris", "Lyon", "Marseille", "Lille", "Nantes"],
           ["Rue de la Paix", "Avenue Victor Hugo", "Rue du Moulin"], "0"),
    "NL": ("B.V.", ["Amsterdam", "Rotterdam", "Utrecht", "Eindhoven"],
           ["Kerkstraat", "Dorpsstraat", "Molenweg"], "0"),
    "ES": ("S.L.", ["Madrid", "Barcelona", "Valencia", "Seville"],
           ["Calle Mayor", "Avenida del Sol", "Calle Real"], ""),
    "IE": ("Teoranta", ["Dublin", "Cork", "Galway"],
           ["Main Street", "Bridge Street", "Mill Road"], "0"),
    "US": ("Inc", ["New York", "Chicago", "Boston", "Seattle"],
           ["Main St", "Oak Ave", "Maple Dr"], ""),
    "IN": ("Pvt Ltd", ["Mumbai", "Bengaluru", "Chennai", "Delhi"],
           ["MG Road", "Anna Salai", "Park Street"], "0"),
}
COUNTRY_WEIGHTS = {"GB": 40, "DE": 15, "FR": 12, "NL": 8, "ES": 7, "IE": 6, "US": 6, "IN": 6}

# Legacy spellings that the value map in config/mapping.yaml can fix
COUNTRY_VARIANTS = {"GB": ["UK", "United Kingdom", "gb", "GBR"], "DE": ["Germany", "DEU", "de"],
                    "FR": ["France", "FRA"], "NL": ["Holland", "Netherlands"],
                    "ES": ["Spain", "ESP"], "IE": ["Ireland", "Eire"], "US": ["USA", "U.S.A."],
                    "IN": ["India", "IND"]}
UNMAPPABLE_COUNTRIES = ["XX", "Atlantis", "EU", "?"]


def postal_code(rng: random.Random, country: str) -> str:
    """Generate a postcode in the correct national format."""
    L = "ABCDEFGHJKLMNPRSTUWXY"
    d = lambda: str(rng.randint(0, 9))  # noqa: E731 - tiny local helper
    if country == "GB":
        return f"{rng.choice(L)}{rng.choice(L)}{rng.randint(1, 9)} {d()}{rng.choice(L)}{rng.choice(L)}"
    if country == "NL":
        return f"{rng.randint(1000, 9999)} {rng.choice(L)}{rng.choice(L)}"
    if country == "IE":
        return f"{rng.choice('DTCHW')}{rng.randint(10, 99)} {rng.choice(L)}{d()}{d()}{d()}"
    if country == "IN":
        return str(rng.randint(100000, 999999))
    return f"{rng.randint(10000, 99999)}"  # DE, FR, ES, US


def phone(rng: random.Random, country: str, cc: str) -> str:
    """A legacy phone number in one of several real-world notations."""
    prefix = COUNTRIES[country][3]
    number = f"{rng.randint(20, 99)} {rng.randint(1000, 9999)} {rng.randint(1000, 9999)}"
    style = rng.choice(["local", "plus", "double_zero", "dashes"])
    if style == "local":
        return f"{prefix}{number}"
    if style == "plus":
        return f"+{cc} {number}"
    if style == "double_zero":
        return f"00{cc} {number}"
    return f"{prefix}{number}".replace(" ", "-")


def slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())[:20]


def make_name_variant(rng: random.Random, name: str, suffix: str) -> tuple[str, str]:
    """Return a 'fuzzy duplicate' version of a company name and how it was changed."""
    base = name[: -len(suffix)].strip() if suffix and name.endswith(suffix) else name
    kind = rng.choice(["typo", "suffix", "case", "ampersand", "spacing"])
    if kind == "typo" and len(base) > 6:
        i = rng.randint(1, len(base) - 3)
        if base[i].isalpha() and base[i + 1].isalpha():
            return base[:i] + base[i + 1] + base[i] + base[i + 2:] + " " + suffix, "typo"
    if kind == "suffix":
        alt = {"Ltd": "Limited", "GmbH": "G.m.b.H.", "Inc": "Incorporated", "B.V.": "BV",
               "S.L.": "SL", "SARL": "S.A.R.L.", "Pvt Ltd": "Private Limited",
               "Teoranta": "Teo."}.get(suffix, "")
        return f"{base} {alt}".strip(), "suffix"
    if kind == "ampersand" and " & " in base:
        return base.replace(" & ", " and ") + " " + suffix, "ampersand"
    if kind == "spacing":
        return "  " + base.replace(" ", "  ") + " " + suffix + " ", "spacing"
    return name.upper(), "case"


def generate(n_base: int, key: str, prefix: int, groups: list[str], rng: random.Random,
             used_names: set) -> list[dict]:
    """Generate clean base records (no issues yet)."""
    rows = []
    countries = list(COUNTRY_WEIGHTS)
    weights = list(COUNTRY_WEIGHTS.values())
    cc_map = {"GB": "44", "DE": "49", "FR": "33", "ES": "34", "NL": "31", "IE": "353",
              "US": "1", "IN": "91"}
    for i in range(n_base):
        country = rng.choices(countries, weights)[0]
        suffix, cities, streets, _ = COUNTRIES[country]
        # unique base name, sometimes with '&' so the ampersand variant can be tested
        while True:
            words = (rng.choice(ADJECTIVES), rng.choice(NOUNS), rng.choice(TRADES))
            joiner = " & " if rng.random() < 0.25 else " "
            core = f"{words[0]} {words[1]}{joiner}{words[2]}"
            # uniqueness ignores the '&' so two different companies never differ only by '&';
            # ECC KNA1-NAME1 / LFA1-NAME1 are CHAR 35, so legacy names never exceed 35
            if words not in used_names and len(f"{core} {suffix}") <= 35:
                used_names.add(words)
                break
        name = f"{core} {suffix}"
        rows.append({
            key: f"{prefix + i:010d}",
            "NAME1": name,
            "NAME2": rng.choice([None, None, None, "Accounts Dept", "c/o Head Office"]),
            "STRAS": f"{rng.randint(1, 250)} {rng.choice(streets)}",
            "ORT01": rng.choice(cities),
            "PSTLZ": postal_code(rng, country),
            "LAND1": country,
            "TELF1": phone(rng, country, cc_map[country]),
            "EMAIL": f"{rng.choice(['info', 'sales', 'accounts', 'orders'])}@{slug(core)}.example",
            "ACCT_GROUP": rng.choice(groups),
            "LOEVM": None,
            "ERDAT": f"{rng.randint(2004, 2022)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "LAST_ACTIVITY": f"{rng.randint(2020, 2025)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
        })
    return rows


def inject_issues(rows: list[dict], obj: str, key: str, counts: dict, rng: random.Random,
                  next_id: int) -> tuple[list[dict], list[dict], list[int]]:
    """Damage a known set of records and log every injected issue (ground truth)."""
    log = []
    # Each record receives at most one issue so detection can be measured cleanly.
    pool = list(range(len(rows)))
    rng.shuffle(pool)

    def take(n):
        picked = pool[:n]
        del pool[:n]
        return picked

    def note(rec, issue, detail):
        log.append({"object": obj, "legacy_id": rec[key], "issue": issue, "detail": detail})

    for i in take(counts["MISSING_MANDATORY"]):
        field = rng.choice(["NAME1", "STRAS", "ORT01", "PSTLZ", "LAND1"])
        rows[i][field] = rng.choice([None, "  "])  # blank or whitespace-only
        note(rows[i], "MISSING_MANDATORY", field)
    for i in take(counts["INVALID_POSTAL_CODE"]):
        bad = rng.choice(["ABC", "1234", "000", "99999999", "N/A"])
        rows[i]["PSTLZ"] = bad
        note(rows[i], "INVALID_POSTAL_CODE", bad)
    for i in take(counts["INVALID_EMAIL"]):
        e = rows[i]["EMAIL"]
        bad = rng.choice([e.replace("@", ""), e.split("@")[0] + "@", e.replace("@", "@@"),
                          e.replace(".example", ""), "n/a"])
        rows[i]["EMAIL"] = bad
        note(rows[i], "INVALID_EMAIL", bad)
    for i in take(counts["INVALID_PHONE"]):
        bad = rng.choice(["12345", "N/A", "TBC", "0", "ext. 204", "+44 12"])
        rows[i]["TELF1"] = bad
        note(rows[i], "INVALID_PHONE", bad)
    for i in take(counts["COUNTRY_VARIANT"]):
        variant = rng.choice(COUNTRY_VARIANTS[rows[i]["LAND1"]])
        rows[i]["LAND1"] = variant
        note(rows[i], "COUNTRY_VARIANT", variant)
    for i in take(counts["INVALID_COUNTRY"]):
        bad = rng.choice(UNMAPPABLE_COUNTRIES)
        rows[i]["LAND1"] = bad
        note(rows[i], "INVALID_COUNTRY", bad)
    for i in take(counts["OBSOLETE"]):
        if rng.random() < 0.5:
            rows[i]["LOEVM"] = "X"
            note(rows[i], "OBSOLETE", "deletion flag LOEVM=X")
        else:
            rows[i]["LAST_ACTIVITY"] = f"{rng.randint(2010, 2018)}-06-30"
            note(rows[i], "OBSOLETE", f"last activity {rows[i]['LAST_ACTIVITY']}")

    # Duplicates: copy a still-clean record with a fuzzy name and slightly different data
    dups = []
    for i in take(counts["DUPLICATE"]):
        original = rows[i]
        dup = dict(original)
        dup[key] = f"{next_id:010d}"
        next_id += 1
        suffix = COUNTRIES[original["LAND1"]][0]
        variant, how = make_name_variant(rng, original["NAME1"], suffix)
        dup["NAME1"] = variant[:35]          # legacy field length
        # duplicates are usually less complete, sometimes newer
        if rng.random() < 0.6:
            dup[rng.choice(["TELF1", "EMAIL", "NAME2"])] = None
        dup["ERDAT"] = f"{rng.randint(2005, 2023)}-{rng.randint(1, 12):02d}-15"
        dups.append(dup)
        log.append({"object": obj, "legacy_id": dup[key], "issue": "DUPLICATE",
                    "detail": f"duplicate of {original[key]} ({how})"})
    return rows + dups, log, pool  # pool = indices still clean


def build(n_customers: int = 1200, n_vendors: int = 400, seed: int = SEED):
    rng = random.Random(seed)
    used_names: set = set()

    customers = generate(n_customers, "KUNNR", 100001, ["Z001", "Z002"], rng, used_names)
    vendors = generate(n_vendors, "LIFNR", 300001, ["Z100", "Z200"], rng, used_names)

    cust_counts = {"MISSING_MANDATORY": 48, "INVALID_POSTAL_CODE": 36, "INVALID_EMAIL": 30,
                   "INVALID_PHONE": 30, "COUNTRY_VARIANT": 150, "INVALID_COUNTRY": 10,
                   "OBSOLETE": 72, "DUPLICATE": 90}
    vend_counts = {"MISSING_MANDATORY": 16, "INVALID_POSTAL_CODE": 12, "INVALID_EMAIL": 10,
                   "INVALID_PHONE": 10, "COUNTRY_VARIANT": 50, "INVALID_COUNTRY": 4,
                   "OBSOLETE": 24, "DUPLICATE": 30}

    customers, cust_log, clean_customers = inject_issues(
        customers, "customer", "KUNNR", cust_counts, rng, 100001 + n_customers)
    vendors, vend_log, _ = inject_issues(
        vendors, "vendor", "LIFNR", vend_counts, rng, 300001 + n_vendors)

    # SHARED_BP: 20 companies that are both customer and vendor (separate legacy numbers).
    # In S/4HANA they must become ONE Business Partner with two roles.
    next_lifnr = 300001 + len(vendors)
    for i in clean_customers[:20]:
        c = customers[i]
        v = {**c, "LIFNR": f"{next_lifnr:010d}", "ACCT_GROUP": "Z100"}
        v.pop("KUNNR")
        next_lifnr += 1
        vendors.append(v)
        vend_log.append({"object": "vendor", "legacy_id": v["LIFNR"], "issue": "SHARED_BP",
                         "detail": f"same company as customer {c['KUNNR']}"})

    cust_df = pd.DataFrame(customers).rename(columns={"ACCT_GROUP": "KTOKD"})
    vend_df = pd.DataFrame(vendors).rename(columns={"ACCT_GROUP": "KTOKK"})
    # Shuffle so duplicates are not next to their originals (like a real extract)
    cust_df = cust_df.sample(frac=1, random_state=seed).reset_index(drop=True)
    vend_df = vend_df.sample(frac=1, random_state=seed).reset_index(drop=True)
    issues = pd.DataFrame(cust_log + vend_log)
    return cust_df, vend_df, issues


if __name__ == "__main__":
    LEGACY_DIR.mkdir(parents=True, exist_ok=True)
    cust, vend, issues = build()
    cust.to_csv(LEGACY_DIR / "kna1_legacy.csv", index=False)
    vend.to_csv(LEGACY_DIR / "lfa1_legacy.csv", index=False)
    issues.to_csv(LEGACY_DIR / "injected_issues.csv", index=False)
    print(f"SYNTHETIC: {len(cust):,} customers, {len(vend):,} vendors, "
          f"{len(issues):,} injected issues logged")
