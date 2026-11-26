"""Render the REAL generated Excel workbook to HTML so it can be screenshotted.

No Excel/LibreOffice is needed: openpyxl reads reports/reconciliation_report.xlsx,
static cell styles are copied, and the workbook's own conditional-formatting
rules (cellIs "equal" fills and data bars) are evaluated here exactly as Excel
would apply them. Output: reports/excel_preview.html

Usage:  python scripts/render_excel.py [sheet ...]
"""

import html
import sys
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "reports" / "reconciliation_report.xlsx"
OUT = ROOT / "reports" / "excel_preview.html"


def rgb(color) -> str | None:
    """openpyxl colour -> '#RRGGBB' (ignores theme/indexed colours)."""
    if color is None or color.type != "rgb" or not isinstance(color.rgb, str):
        return None
    value = color.rgb[-6:]
    return None if value == "000000" and color.rgb.startswith("00") else f"#{value}"


def conditional_styles(ws) -> dict:
    """Evaluate the sheet's conditional formatting -> {(row, col): css}."""
    styles = {}
    for cf in ws.conditional_formatting:
        cells = [(r, c) for rng in cf.sqref.ranges for r in range(rng.min_row, rng.max_row + 1)
                 for c in range(rng.min_col, rng.max_col + 1)]
        for rule in cf.rules:
            if rule.type == "cellIs" and rule.operator == "equal":
                target = rule.formula[0].strip('"')
                fill = rule.dxf.fill
                colour = rgb(fill.bgColor) or rgb(fill.fgColor)
                for r, c in cells:
                    if str(ws.cell(r, c).value) == target and colour:
                        styles[(r, c)] = f"background:{colour};"
            elif rule.type == "dataBar":
                values = [ws.cell(r, c).value for r, c in cells]
                numbers = [v for v in values if isinstance(v, (int, float))]
                top = max(numbers) if numbers else 0
                colour = rgb(rule.dataBar.color) or "#638EC6"
                for (r, c), v in zip(cells, values):
                    if isinstance(v, (int, float)) and top > 0:
                        pct = 100 * v / top
                        styles[(r, c)] = (f"background:linear-gradient(90deg,{colour}99 {pct:.0f}%,"
                                          f"transparent {pct:.0f}%);")
    return styles


def sheet_html(ws, max_rows: int = 40, max_cols: int = 11) -> str:
    cond = conditional_styles(ws)
    n_rows, n_cols = min(ws.max_row, max_rows), min(ws.max_column, max_cols)
    widths = [min((ws.column_dimensions[get_column_letter(c)].width or 10) * 7, 330) for c in range(1, n_cols + 1)]
    out = [f"<table class='grid' style='width:{sum(widths) + 32:.0f}px'><tr><th class='corner'></th>"]
    out += [f"<th style='width:{w:.0f}px'>{get_column_letter(c)}</th>" for c, w in enumerate(widths, 1)]
    out.append("</tr>")
    for r in range(1, n_rows + 1):
        out.append(f"<tr><th class='rown'>{r}</th>")
        for c in range(1, n_cols + 1):
            cell = ws.cell(r, c)
            css = ""
            if cell.fill and cell.fill.fill_type == "solid":
                colour = rgb(cell.fill.fgColor)
                css += f"background:{colour};" if colour else ""
            if cell.font is not None:
                if cell.font.b:
                    css += "font-weight:600;"
                if cell.font.i:
                    css += "font-style:italic;"
                colour = rgb(cell.font.color) if cell.font.color is not None else None
                css += f"color:{colour};" if colour else ""
                if cell.font.sz and cell.font.sz > 11:
                    css += f"font-size:{cell.font.sz + 2}px;"
            css += cond.get((r, c), "")
            value = cell.value
            if isinstance(value, float):
                value = f"{value:,.2f}"
            elif isinstance(value, int):
                value = f"{value:,}"
                css += "text-align:right;"
            text = html.escape("" if value is None else str(value))
            out.append(f"<td style='{css}'>{text}</td>")
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def render(sheets: list[str]) -> Path:
    wb = load_workbook(WORKBOOK)
    tabs = "".join(f"<span class='tab{' active' if name == sheets[0] else ''}'>{html.escape(name)}</span>"
                   for name in wb.sheetnames)
    body = []
    for name in sheets:
        body.append(f"<div class='title'>reconciliation_report.xlsx &mdash; sheet <b>{name}</b></div>")
        body.append(sheet_html(wb[name]))
    page = f"""<html><head><meta charset='utf-8'><style>
    body{{font-family:Calibri,'Segoe UI',Arial,sans-serif;font-size:13px;margin:0;background:#fff}}
    .bar{{background:#217346;color:#fff;padding:8px 14px;font-size:14px}}
    .title{{padding:8px 12px;color:#333;background:#f3f3f3;border-bottom:1px solid #d4d4d4}}
    .grid{{border-collapse:collapse;table-layout:fixed}}
    .grid th{{background:#f3f3f3;color:#555;font-weight:normal;border:1px solid #d4d4d4;padding:2px 4px}}
    .grid td{{border:1px solid #e1e1e1;padding:2px 5px;white-space:nowrap;overflow:hidden;
             text-overflow:ellipsis;max-width:330px;height:19px}}
    .rown{{width:30px}} .corner{{width:30px}}
    .tabs{{background:#f3f3f3;border-top:1px solid #d4d4d4;padding:4px 8px}}
    .tab{{display:inline-block;padding:3px 12px;margin-right:2px;color:#444}}
    .tab.active{{background:#fff;border-bottom:3px solid #217346;color:#217346;font-weight:600}}
    </style></head><body><div class='bar'>Excel workbook preview (rendered from the generated .xlsx)</div>
    {''.join(body)}<div class='tabs'>{tabs}</div></body></html>"""
    OUT.write_text(page, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print(render(sys.argv[1:] or ["Summary"]))
