"""MigrateRight sign-off dashboard (Streamlit).

Reads the tables written by the pipeline (SQLite by default, PostgreSQL via
MIGRATERIGHT_DB_URL) so a business user can review and sign off a load.

Run:  streamlit run app/dashboard.py --server.port 8540
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import text

# make 'src' importable when started with `streamlit run app/dashboard.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import METRICS_PATH, REPORTS_DIR, get_engine  # noqa: E402
from src.load import read_sql  # noqa: E402

st.set_page_config(page_title="MigrateRight - Reconciliation", page_icon="✅", layout="wide")
engine = get_engine()

OBJECT_LABEL = {"customer": "Customers (KNA1 → BP)", "vendor": "Vendors (LFA1 → BP)",
                "material": "Materials (MARA → Product)"}
STATUS_COLOURS = {"PASS": "background-color:#c6efce", "FAIL": "background-color:#ffc7ce",
                  "MATCH": "background-color:#c6efce", "TRANSFORMED": "background-color:#ffeb9c",
                  "MISMATCH": "background-color:#ffc7ce"}


def colour(value):
    return STATUS_COLOURS.get(value, "")


@st.cache_data(ttl=60)
def table(query: str) -> pd.DataFrame:
    return read_sql(engine, query)


def load_metrics() -> dict:
    return json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else {}


try:
    summary = table("SELECT * FROM mig_recon_summary")
except Exception:
    st.error("No pipeline results found. Run `python -m src.pipeline` first.")
    st.stop()

metrics = load_metrics()

# ---------------------------------------------------------------- sidebar
st.sidebar.title("MigrateRight")
st.sidebar.caption("Case study: SAP ECC → S/4HANA master-data migration")
page = st.sidebar.radio("View", ["Reconciliation", "Rejected records", "Duplicates merged",
                                 "Data profiling", "Sign-off"])
st.sidebar.markdown("---")
st.sidebar.write(f"**Target DB:** {engine.dialect.name}")
if metrics:
    st.sidebar.write(f"**Run:** {metrics['generated_at'].replace('T', ' ')[:16]} UTC")
st.sidebar.caption("Real public data. Customers/vendors: Olist Brazilian E-Commerce (Kaggle, CC BY-NC-SA 4.0). "
                   "Materials: Online Retail II (UCI/Kaggle, CC BY 4.0).")

# ---------------------------------------------------------------- pages
if page == "Reconciliation":
    st.title("Load reconciliation")
    totals = metrics.get("totals", {})
    c = st.columns(5)
    c[0].metric("Records in", f"{summary['records_in'].sum():,}")
    c[1].metric("Loaded", f"{summary['loaded'].sum():,}")
    c[2].metric("Quarantined", f"{summary['quarantined'].sum():,}",
                help=f"{100 * summary['quarantined'].sum() / summary['records_in'].sum():.1f}% of records in")
    c[3].metric("Duplicates merged", f"{summary['duplicates_merged'].sum():,}")
    c[4].metric("Checks passed", f"{summary['checks_passed'].sum()}/{summary['checks_total'].sum()}")

    st.subheader("Records by object")
    st.dataframe(summary.style.map(colour, subset=["status"]).format({"rejected_pct": "{:.2f}%"}),
                 hide_index=True, width="stretch")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Where every legacy record went")
        outcome = summary.set_index("object")[["loaded", "quarantined", "duplicates_merged"]]
        st.bar_chart(outcome, horizontal=True, height=260,
                     color=["#2f9e44", "#e03131", "#0a6ed1"])
    with right:
        st.subheader("Business Partners")
        st.metric("BPs created", f"{totals.get('business_partners_created', 0):,}")
        loc = metrics.get("real_data_findings", {}).get("location_only_matcher_vs_unique_id", {})
        if loc:
            st.metric("Location-only dedup precision", f"{loc['precision_pct']}%",
                      help="Pairs found by zip + city alone vs. the real customer_unique_id - why we merge on the id")

    st.subheader("Reconciliation checks")
    obj = st.selectbox("Object", list(OBJECT_LABEL), format_func=OBJECT_LABEL.get)
    checks = table("SELECT * FROM mig_recon_checks")
    st.dataframe(checks[checks["object"] == obj].drop(columns="object").style.map(colour, subset=["status"]),
                 hide_index=True, width="stretch")
    with st.expander("Sample comparison: legacy value vs loaded value"):
        sample = table("SELECT * FROM mig_recon_sample")
        st.dataframe(sample[sample["object"] == obj].drop(columns="object").style.map(colour, subset=["result"]),
                     hide_index=True, width="stretch")

elif page == "Rejected records":
    st.title("Rejected records (quarantine)")
    st.caption("Records that failed a rule in config/rules.yaml. They are not loaded, never dropped: "
               "fix them in the legacy system or the rule, then re-run.")
    quarantine = table("SELECT * FROM mig_quarantine")
    reasons = table("SELECT * FROM mig_reason_summary")
    f1, f2 = st.columns(2)
    objects = f1.multiselect("Object", sorted(quarantine["object"].unique()),
                             default=["customer", "vendor"])
    rules = f2.multiselect("Reason", sorted(quarantine["rule"].unique()))
    view = quarantine[quarantine["object"].isin(objects)] if objects else quarantine
    if rules:
        view = view[view["rule"].isin(rules)]
    left, right = st.columns([2, 3])
    with left:
        st.subheader("% of records in, by reason")
        chart = reasons[reasons["object"].isin(objects or reasons["object"].unique())]
        pivot = chart.pivot_table(index="rule", columns="object", values="pct_of_records_in", fill_value=0)
        st.bar_chart(pivot, horizontal=True, height=320)
    with right:
        st.subheader(f"{view['legacy_id'].nunique():,} records, {len(view):,} rule failures")
        st.dataframe(view, hide_index=True, width="stretch", height=320)
    st.download_button("Download rejection list (CSV)", view.to_csv(index=False), "rejections.csv",
                       "text/csv")

elif page == "Duplicates merged":
    st.title("Duplicates merged")
    st.caption("Customers: many Olist customer_id rows belong to one customer_unique_id -> merged; survivor = "
               "newest order (latest address). Materials: codes differing only in case; survivor = most sales.")
    merges = table("SELECT * FROM mig_merge_log")
    names = pd.concat([
        table("SELECT kunnr AS id, ort01 || ' ' || pstlz || ' (' || erdat || ')' AS name FROM src_customer"),
        table("SELECT lifnr AS id, ort01 AS name FROM src_vendor"),
        table("SELECT matnr AS id, maktx AS name FROM src_material")])
    lookup = dict(zip(names["id"], names["name"]))
    merges["survivor_name"] = merges["survivor_id"].map(lookup)
    merges["merged_name"] = merges["merged_id"].map(lookup)
    obj = st.radio("Object", ["customer", "vendor", "material"], horizontal=True)
    view = merges[merges["object"] == obj][["survivor_id", "survivor_name", "merged_id", "merged_name",
                                            "score", "match_reason"]]
    st.metric("Merged into survivors", len(view))
    st.dataframe(view, hide_index=True, width="stretch")

elif page == "Data profiling":
    st.title("Legacy data profiling")
    profile = table("SELECT * FROM mig_profile")
    obj = st.radio("Object", ["customer", "vendor", "material"], horizontal=True)
    st.dataframe(profile[profile["object"] == obj].drop(columns="object"), hide_index=True, width="stretch",
                 column_config={
                     "filled_pct": st.column_config.ProgressColumn("Completeness %", min_value=0, max_value=100),
                     "validity_pct": st.column_config.ProgressColumn("Validity %", min_value=0, max_value=100)})
    report = REPORTS_DIR / "profiling_report.html"
    if report.exists():
        st.download_button("Download full HTML profiling report", report.read_bytes(), "profiling_report.html")

else:
    st.title("Business sign-off")
    status = "PASS" if (summary["status"] == "PASS").all() else "FAIL"
    (st.success if status == "PASS" else st.error)(f"Reconciliation status: {status}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS mig_signoff (signed_at VARCHAR(19), name VARCHAR(80), "
                          "role VARCHAR(80), decision VARCHAR(10), comment VARCHAR(500))"))
    with st.form("signoff"):
        name = st.text_input("Name")
        role = st.selectbox("Role", ["Customer master owner", "Vendor master owner", "Product master owner",
                                     "Migration lead"])
        decision = st.radio("Decision", ["Approve", "Reject"], horizontal=True)
        comment = st.text_area("Comment")
        if st.form_submit_button("Record sign-off") and name:
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO mig_signoff VALUES (:t, :n, :r, :d, :c)"),
                             {"t": f"{datetime.now():%Y-%m-%d %H:%M:%S}", "n": name, "r": role,
                              "d": decision, "c": comment})
            st.success("Sign-off recorded.")
    st.dataframe(read_sql(engine, "SELECT * FROM mig_signoff ORDER BY signed_at DESC"), hide_index=True,
                 width="stretch")
    workbook = REPORTS_DIR / "reconciliation_report.xlsx"
    if workbook.exists():
        st.download_button("Download Excel reconciliation workbook", workbook.read_bytes(),
                           "reconciliation_report.xlsx")
