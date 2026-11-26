"""Shared paths, YAML loading and the database connection."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
LEGACY_DIR = ROOT / "data" / "legacy"     # committed legacy extracts (CSV)
REPORTS_DIR = ROOT / "reports"            # generated reports (gitignored)
METRICS_PATH = ROOT / "metrics.json"

# Read .env if present (never committed); real environment variables win.
load_dotenv(ROOT / ".env")

DEFAULT_DB_URL = f"sqlite:///{(ROOT / 'data' / 'migrateright.db').as_posix()}"

OBJECTS = ["customer", "vendor", "material"]


def load_yaml(name: str) -> dict:
    """Load config/<name>.yaml into a dict."""
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_rules() -> dict:
    return load_yaml("rules.yaml")


def load_mapping() -> dict:
    return load_yaml("mapping.yaml")


def db_url() -> str:
    """PostgreSQL if MIGRATERIGHT_DB_URL is set, otherwise the local SQLite file."""
    url = os.getenv("MIGRATERIGHT_DB_URL", "").strip()
    if not url or url.startswith("sqlite:///data/"):
        # A relative SQLite path is resolved against the project root.
        return DEFAULT_DB_URL if not url else f"sqlite:///{(ROOT / url[10:]).as_posix()}"
    return url


def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or db_url())
