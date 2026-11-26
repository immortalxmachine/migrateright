"""Shared pytest fixtures.

Tests use a temporary SQLite database, or PostgreSQL when MIGRATERIGHT_DB_URL
points to one (that is how CI runs them against a postgres service container).
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from src.config import load_mapping, load_rules

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def rules():
    return load_rules()


@pytest.fixture(scope="session")
def mapping():
    return load_mapping()


@pytest.fixture()
def engine(tmp_path):
    url = os.getenv("MIGRATERIGHT_DB_URL", "")
    if url.startswith("postgresql"):
        return create_engine(url)
    return create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
