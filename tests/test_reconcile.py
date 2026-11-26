"""End-to-end run on the tiny fixtures: every legacy record is accounted for."""

import json

import pandas as pd
from sqlalchemy import text

from src.config import load_mapping
from src.load import scalar
from src.pipeline import run
from src.reconcile import reconcile_object
from tests.conftest import FIXTURES

# expected outcome per object for the fixtures (see tests/fixtures/*.csv)
EXPECTED = {
    "customer": {"records_in": 6, "records_loaded": 3, "records_quarantined": 2, "duplicates_merged": 1},
    "vendor": {"records_in": 7, "records_loaded": 3, "records_quarantined": 4, "duplicates_merged": 0},
    "material": {"records_in": 8, "records_loaded": 2, "records_quarantined": 5, "duplicates_merged": 1},
}


def run_fixtures(engine, tmp_path):
    return run(engine=engine, legacy_folder=FIXTURES, reports_dir=tmp_path,
               metrics_path=tmp_path / "metrics.json", evaluate=False)


def test_pipeline_counts_balance(engine, tmp_path):
    metrics = run_fixtures(engine, tmp_path)
    for obj, expected in EXPECTED.items():
        got = {k: metrics["objects"][obj][k] for k in expected}
        assert got == expected, obj
        # records in = loaded + quarantined + merged  (nothing silently dropped)
        assert got["records_in"] == got["records_loaded"] + got["records_quarantined"] + got["duplicates_merged"]
    assert metrics["totals"]["business_partners_created"] == 6
    assert metrics["objects"]["vendor"]["rejected_records_by_reason"]["ZIP_STATE_MISMATCH"] == 2
    assert metrics["objects"]["material"]["rejected_records_by_reason"]["NON_PRODUCT"] == 1
    assert metrics["overall_status"] == "PASS"
    assert json.loads((tmp_path / "metrics.json").read_text())["overall_status"] == "PASS"
    assert (tmp_path / "reconciliation_report.xlsx").exists()
    assert (tmp_path / "profiling_report.html").exists()


def test_target_counts_via_sql(engine, tmp_path):
    run_fixtures(engine, tmp_path)
    assert scalar(engine, "SELECT COUNT(*) FROM tgt_but000") == 6     # 3 customers + 3 vendors
    assert scalar(engine, "SELECT COUNT(*) FROM tgt_but100") == 6     # 3 x FLCU01 + 3 x FLVN01
    assert scalar(engine, "SELECT COUNT(*) FROM tgt_mara") == 2
    city = scalar(engine, """SELECT a.city1 FROM tgt_adrc a
                             JOIN tgt_but020 r ON r.addrnumber = a.addrnumber
                             JOIN tgt_cvi_vend_link l ON l.partner = r.partner
                             WHERE l.lifnr = 's0000000000000000000000000000004'""")
    assert city == "São Paulo"                                       # legacy typo 'sao pauo' corrected
    assert scalar(engine, "SELECT COUNT(*) FROM mig_recon_checks WHERE status = 'FAIL'") == 0


def test_reconciliation_detects_a_lost_record(engine, tmp_path):
    """If a loaded row disappears from the target, the balance checks must FAIL."""
    run_fixtures(engine, tmp_path)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tgt_mara WHERE matnr = '22423'"))
    survivors = pd.DataFrame({"LEGACY_ID": ["85123A", "22423"], "MATNR": ["85123A", "22423"],
                              "MATNR_LEGACY": ["85123A", "22423"], "MTART": "HAWA", "MEINS": "PC",
                              "MAKTX": "X", "STPRS": 1.0, "ERSDA": "2010-01-01"})
    checks, _ = reconcile_object(engine, "material", 8, survivors, load_mapping())
    status = {c["check"]: c["status"] for c in checks}
    assert status["Records in = loaded + quarantined + merged"] == "FAIL"
    assert status["Legacy ids not accounted for"] == "FAIL"
