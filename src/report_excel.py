"""Excel reconciliation workbook for business sign-off (openpyxl).

Sheets: Summary | Customers | Vendors | Materials | Rejections | Duplicates | Sign-off
Conditional formatting: PASS green / FAIL red, MATCH / TRANSFORMED / MISMATCH
colours, data bars on rejection percentages.
"""

from datetime import datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="0A6ED1")       # SAP-like blue
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14, color="0A3D62")
GREEN = PatternFill("solid", fgColor="C6EFCE")
RED = PatternFill("solid", fgColor="FFC7CE")
AMBER = PatternFill("solid", fgColor="FFEB9C")
THIN = Border(bottom=Side(style="thin", color="D9D9D9"))


def write_table(ws, df: pd.DataFrame, start_row: int, title: str | None = None) -> tuple[int, int]:
    """Write a DataFrame with a styled header. Returns (first data row, last row)."""
    row = start_row
    if title:
        ws.cell(row=row, column=1, value=title).font = Font(bold=True, size=12)
        row += 1
    for c, name in enumerate(df.columns, start=1):
        cell = ws.cell(row=row, column=c, value=str(name))
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
    for r, values in enumerate(df.itertuples(index=False), start=row + 1):
        for c, value in enumerate(values, start=1):
            if isinstance(value, float) and pd.isna(value):
                value = None
            ws.cell(row=r, column=c, value=value).border = THIN
    return row + 1, row + len(df)


def colour_status(ws, col_letter: str, first: int, last: int) -> None:
    """Conditional formatting on a status column (evaluated by Excel at open)."""
    rng = f"{col_letter}{first}:{col_letter}{max(first, last)}"
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"PASS"'], fill=GREEN))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"FAIL"'], fill=RED))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"MATCH"'], fill=GREEN))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"TRANSFORMED"'], fill=AMBER))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"MISMATCH"'], fill=RED))


def data_bar(ws, col_letter: str, first: int, last: int, color: str = "F08C00") -> None:
    rng = f"{col_letter}{first}:{col_letter}{max(first, last)}"
    ws.conditional_formatting.add(rng, DataBarRule(start_type="num", start_value=0,
                                                   end_type="max", color=color))


def autosize(ws, max_width: int = 60) -> None:
    widths = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                widths[cell.column] = max(widths.get(cell.column, 0), len(str(cell.value)))
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = min(max(10, width + 2), max_width)


def col_of(df: pd.DataFrame, name: str) -> str:
    return get_column_letter(list(df.columns).index(name) + 1)


def build_workbook(path, summary: pd.DataFrame, reasons: pd.DataFrame, checks: pd.DataFrame,
                   samples: pd.DataFrame, quarantine: pd.DataFrame, merges: pd.DataFrame,
                   db_backend: str) -> None:
    wb = Workbook()

    # ---------------- Summary
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "MigrateRight - ECC to S/4HANA master data reconciliation"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Run: {datetime.now():%Y-%m-%d %H:%M}   |   Target DB: {db_backend}   |   " \
               "Case study - customers/vendors: Olist (CC BY-NC-SA 4.0); materials: Online Retail II (CC BY 4.0)"
    ws["A2"].font = Font(italic=True, color="52606D")
    first, last = write_table(ws, summary, 4, "Records by object")
    colour_status(ws, col_of(summary, "status"), first, last)
    data_bar(ws, col_of(summary, "rejected_pct"), first, last)
    first, last = write_table(ws, reasons, last + 3, "Quarantined records by reason")
    data_bar(ws, col_of(reasons, "pct_of_records_in"), first, last, color="E03131")
    ws.freeze_panes = "A5"
    autosize(ws)
    ws.column_dimensions["A"].width = 14

    # ---------------- one sheet per object: checks + sample comparison
    for obj, title in (("customer", "Customers"), ("vendor", "Vendors"), ("material", "Materials")):
        ws = wb.create_sheet(title)
        ws["A1"] = f"{title}: reconciliation checks"
        ws["A1"].font = TITLE_FONT
        obj_checks = checks[checks["object"] == obj].drop(columns="object")
        first, last = write_table(ws, obj_checks, 3)
        colour_status(ws, col_of(obj_checks, "status"), first, last)
        obj_sample = samples[samples["object"] == obj].drop(columns="object")
        if not obj_sample.empty:
            first, last = write_table(ws, obj_sample, last + 3,
                                      "Sample comparison: legacy value vs loaded target value")
            colour_status(ws, col_of(obj_sample, "result"), first, last)
        ws.freeze_panes = "A4"
        autosize(ws)

    # ---------------- Rejections (every failed rule) and Duplicates (merge log)
    for title, df in (("Rejections", quarantine), ("Duplicates", merges)):
        ws = wb.create_sheet(title)
        first, last = write_table(ws, df, 1)
        ws.auto_filter.ref = f"A1:{get_column_letter(len(df.columns))}{max(1, last)}"
        ws.freeze_panes = "A2"
        if title == "Duplicates" and not df.empty:
            data_bar(ws, col_of(df, "score"), first, last, color="0A6ED1")
        autosize(ws)

    # ---------------- Sign-off
    ws = wb.create_sheet("Sign-off")
    ws["A1"] = "Business sign-off"
    ws["A1"].font = TITLE_FONT
    ws["A3"] = "I confirm the reconciliation results above are complete and correct for this load."
    for i, label in enumerate(["Object owner", "Name", "Role", "Date", "Decision (Approve / Reject)",
                               "Comment"], start=5):
        ws.cell(row=i, column=1, value=label).font = Font(bold=True)
        ws.cell(row=i, column=2).border = Border(bottom=Side(style="thin"))
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 50

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
