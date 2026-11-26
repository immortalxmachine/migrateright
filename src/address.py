"""Address standardisation against the Olist geolocation reference.

For each record we look up its 5-digit zip prefix in data/legacy/geo_reference.csv
(built from olist_geolocation) and try to match the typed city to a city known
for that zip prefix:

  exact    city key ('sao paulo') is one of the zip prefix's cities
  fuzzy    rapidfuzz ratio >= threshold (typos: 'sao pauo', 'floranopolis')
  cleaned  typed text had extra parts ('mogi das cruzes / sp', 'lages - sc') -> retry on the first part
  none     no match -> validation quarantines it (CITY_ZIP_MISMATCH)

The matched city is replaced by the reference spelling ('são paulo' -> 'São Paulo').
"""

import re

import pandas as pd
from rapidfuzz import fuzz, process

from src.extract import city_key

PARTICLES = {"da", "das", "de", "del", "do", "dos", "e", "d"}


def pretty_city(name: str) -> str:
    """'são joão del rei' -> 'São João del Rei' (Portuguese particles stay lower case)."""
    words = str(name).strip().lower().split()
    return " ".join(w if (i > 0 and w in PARTICLES) else w[:1].upper() + w[1:] for i, w in enumerate(words))


class GeoReference:
    """Fast lookups built once from the reference table."""

    def __init__(self, geo: pd.DataFrame):
        self.cities = {}            # zip prefix -> {city_key: pretty spelling}
        for zip_prefix, key, city in zip(geo["ZIP_PREFIX"], geo["CITY_KEY"], geo["CITY"]):
            self.cities.setdefault(zip_prefix, {})[key] = pretty_city(city)
        # zip prefix -> state (UF) with the most geolocation points
        points = (geo.assign(POINTS=geo["POINTS"].astype(int))
                  .groupby(["ZIP_PREFIX", "REGIO"])["POINTS"].sum().reset_index()
                  .sort_values(["ZIP_PREFIX", "POINTS"], ascending=[True, False])
                  .drop_duplicates("ZIP_PREFIX"))
        self.state = dict(zip(points["ZIP_PREFIX"], points["REGIO"]))

    def match_city(self, zip_prefix, city, threshold: int):
        """Return (standard city or None, method, score)."""
        candidates = self.cities.get(zip_prefix)
        if not candidates or city is None:
            return None, "none", 0.0
        key = city_key(city)
        if key in candidates:
            return candidates[key], "exact", 100.0
        best = process.extractOne(key, list(candidates), scorer=fuzz.ratio)
        if best and best[1] >= threshold:
            return candidates[best[0]], "fuzzy", round(best[1], 1)
        # 'mogi das cruzes / sp', 'lages - sc', 'novo hamburgo, rio grande do sul, brasil'
        first_part = city_key(re.split(r"[/\\,\-(]", str(city))[0])
        if first_part and first_part != key:
            if first_part in candidates:
                return candidates[first_part], "cleaned", 100.0
            best = process.extractOne(first_part, list(candidates), scorer=fuzz.ratio)
            if best and best[1] >= threshold:
                return candidates[best[0]], "cleaned", round(best[1], 1)
        return None, "none", round(best[1], 1) if best else 0.0


def standardise_addresses(df: pd.DataFrame, geo: GeoReference, spec: dict) -> pd.DataFrame:
    """Add CITY_STD, CITY_MATCH, CITY_SCORE and GEO_REGIO columns (input not modified)."""
    out = df.copy()
    zip_field, city_field = spec["zip_field"], spec["city_field"]
    results = [geo.match_city(z, c, spec["city_fuzzy_threshold"]) for z, c in zip(out[zip_field], out[city_field])]
    out["CITY_STD"] = [r[0] for r in results]
    out["CITY_MATCH"] = [r[1] for r in results]
    out["CITY_SCORE"] = [r[2] for r in results]
    out["GEO_REGIO"] = [geo.state.get(z) for z in out[zip_field]]
    return out
