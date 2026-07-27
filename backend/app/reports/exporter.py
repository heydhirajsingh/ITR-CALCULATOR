"""Local report generation in CSV, Excel, JSON and PDF formats."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models.entities import (
    CapitalGain,
    Deduction,
    Dividend,
    Document,
    Expense,
    Interest,
    TaxYear,
    Transaction,
    TransactionDirection,
)
from backend.app.services.reconciliation_service import reconciliation_service
from backend.app.services.summary_service import summary_service


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

# Slate-900 header background (r, g, b) in 0-1 range
_HDR_BG = (0.118, 0.161, 0.235)
# Accent stripe
_ACCENT = (0.227, 0.565, 0.922)
# Alternating row colours
_ROW_EVEN = (0.973, 0.980, 0.992)
_ROW_ODD = (1.0, 1.0, 1.0)
# Border line colour
_BORDER = (0.878, 0.902, 0.937)
# Muted text
_MUTED = (0.459, 0.525, 0.596)
# White
_WHITE = (1.0, 1.0, 1.0)
# Dark text
_DARK = (0.078, 0.102, 0.149)
# Positive / Negative highlight
_POS = (0.047, 0.557, 0.298)
_NEG = (0.773, 0.114, 0.114)

# Numeric column name fragments – these will be right-aligned and formatted
_NUMERIC_HINTS = {
    "amount", "credit", "debit", "tds", "gain", "quantity",
    "value", "savings", "eligible", "claimed", "total", "count",
    "transactions", "credits", "debits", "confidence",
    "tax", "rebate", "cess", "surcharge", "income", "salary",
    "gross", "net", "estimated",
}


def _is_numeric_col(col: str) -> bool:
    lower = col.lower().replace("_", " ")
    return any(hint in lower for hint in _NUMERIC_HINTS)


def _fmt(value: Any, col: str) -> str:
    """Format a cell value for PDF display."""
    if value is None or value == "":
        return "—"
    if _is_numeric_col(col):
        try:
            fval = float(value)
            return f"{fval:,.2f}"
        except (ValueError, TypeError):
            pass
    text = str(value)
    # Truncate long strings with ellipsis
    if len(text) > 42:
        return text[:40] + "…"
    return text


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

class _PdfWriter:
    """Draws a styled table across multiple A4 pages."""

    # Page geometry (landscape A4 by default)
    PAGE_W = 842.0
    PAGE_H = 595.0
    MARGIN = 36.0
    HEADER_H = 68.0
    FOOTER_H = 22.0
    ROW_H = 14.0
    COL_HDR_H = 18.0

    def __init__(self, title: str, rows: list[dict], columns: list[str]) -> None:
        self.title = title
        self.rows = rows
        self.columns = columns
        self.doc = fitz.open()
        self._total_pages = 0

        # Switch to portrait for narrow tables
        col_count = len(columns)
        if col_count <= 4:
            self.PAGE_W, self.PAGE_H = 595.0, 842.0

        # Compute column widths
        self._col_widths = self._calc_col_widths()

        # Build pages
        self._build()

        # Stamp page numbers
        self._stamp_page_numbers()

    # ------------------------------------------------------------------
    def _calc_col_widths(self) -> list[float]:
        usable = self.PAGE_W - 2 * self.MARGIN
        cols = self.columns
        # Minimum width per col (characters * approx char width at fontsize 7)
        char_w = 4.5
        min_w = [max(len(c) * char_w + 8, 32) for c in cols]
        # Sample data widths
        for row in self.rows[:200]:
            for i, c in enumerate(cols):
                w = len(_fmt(row.get(c, ""), c)) * char_w + 8
                if w > min_w[i]:
                    min_w[i] = w
        total_min = sum(min_w)
        if total_min <= usable:
            # Scale up proportionally to fill usable width
            scale = usable / total_min
            return [w * scale for w in min_w]
        # Scale down to fit
        scale = usable / total_min
        return [max(w * scale, 20) for w in min_w]

    # ------------------------------------------------------------------
    def _new_page(self) -> fitz.Page:
        page = self.doc.new_page(width=self.PAGE_W, height=self.PAGE_H)
        self._total_pages += 1
        self._draw_page_frame(page)
        return page

    def _draw_page_frame(self, page: fitz.Page) -> None:
        """Draw header bar and footer bar on a fresh page."""
        # --- Top header band ---
        hdr_rect = fitz.Rect(0, 0, self.PAGE_W, self.HEADER_H)
        page.draw_rect(hdr_rect, color=None, fill=_HDR_BG)

        # Accent stripe at very top
        page.draw_rect(
            fitz.Rect(0, 0, self.PAGE_W, 4),
            color=None, fill=_ACCENT,
        )

        # Title text
        page.insert_textbox(
            fitz.Rect(self.MARGIN, 10, self.PAGE_W - self.MARGIN, 44),
            self.title,
            fontsize=16,
            fontname="helv",
            color=_WHITE,
            align=fitz.TEXT_ALIGN_LEFT,
        )

        # Subtitle
        now_str = datetime.now().strftime("%d %B %Y  %H:%M")
        page.insert_textbox(
            fitz.Rect(self.MARGIN, 44, self.PAGE_W - 180, self.HEADER_H - 4),
            f"Generated locally on {now_str}   •   Local ITR Preparation",
            fontsize=7.5,
            fontname="helv",
            color=_ACCENT,
            align=fitz.TEXT_ALIGN_LEFT,
        )

        # Row count badge
        count_text = f"{len(self.rows)} record{'s' if len(self.rows) != 1 else ''}"
        page.insert_textbox(
            fitz.Rect(self.PAGE_W - 180, 44, self.PAGE_W - self.MARGIN, self.HEADER_H - 4),
            count_text,
            fontsize=7.5,
            fontname="helv",
            color=_MUTED,
            align=fitz.TEXT_ALIGN_RIGHT,
        )

        # --- Footer bar ---
        footer_y = self.PAGE_H - self.FOOTER_H
        page.draw_line(
            fitz.Point(self.MARGIN, footer_y),
            fitz.Point(self.PAGE_W - self.MARGIN, footer_y),
            color=_BORDER, width=0.5,
        )
        page.insert_textbox(
            fitz.Rect(self.MARGIN, footer_y + 4, self.PAGE_W - self.MARGIN, self.PAGE_H - 2),
            "CONFIDENTIAL  •  For tax preparation purposes only",
            fontsize=6.5,
            fontname="helv",
            color=_MUTED,
            align=fitz.TEXT_ALIGN_LEFT,
        )
        # Page number placeholder (filled in later)
        page.insert_textbox(
            fitz.Rect(self.PAGE_W - 120, footer_y + 4, self.PAGE_W - self.MARGIN, self.PAGE_H - 2),
            f"Page {self._total_pages}",  # will be overwritten after all pages built
            fontsize=6.5,
            fontname="helv",
            color=_MUTED,
            align=fitz.TEXT_ALIGN_RIGHT,
        )

    def _stamp_page_numbers(self) -> None:
        total = self.doc.page_count
        footer_y = self.PAGE_H - self.FOOTER_H
        for i, page in enumerate(self.doc, start=1):
            # White-out the old placeholder
            rect = fitz.Rect(self.PAGE_W - 120, footer_y + 2, self.PAGE_W - self.MARGIN + 2, self.PAGE_H - 1)
            page.draw_rect(rect, color=None, fill=_WHITE)
            page.insert_textbox(
                rect,
                f"Page {i} of {total}",
                fontsize=6.5,
                fontname="helv",
                color=_MUTED,
                align=fitz.TEXT_ALIGN_RIGHT,
            )

    # ------------------------------------------------------------------
    def _draw_col_header(self, page: fitz.Page, y: float) -> None:
        x = self.MARGIN
        for col, w in zip(self.columns, self._col_widths):
            cell_rect = fitz.Rect(x, y, x + w, y + self.COL_HDR_H)
            page.draw_rect(cell_rect, color=None, fill=_HDR_BG)
            label = col.replace("_", " ").title()
            align = fitz.TEXT_ALIGN_RIGHT if _is_numeric_col(col) else fitz.TEXT_ALIGN_LEFT
            page.insert_textbox(
                fitz.Rect(x + 4, y + 3, x + w - 4, y + self.COL_HDR_H - 1),
                label,
                fontsize=7,
                fontname="helv",
                color=_WHITE,
                align=align,
            )
            x += w
        # Bottom border of column header
        page.draw_line(
            fitz.Point(self.MARGIN, y + self.COL_HDR_H),
            fitz.Point(self.MARGIN + sum(self._col_widths), y + self.COL_HDR_H),
            color=_ACCENT, width=1.2,
        )

    def _draw_row(self, page: fitz.Page, row: dict, y: float, even: bool) -> None:
        bg = _ROW_EVEN if even else _ROW_ODD
        x = self.MARGIN
        total_w = sum(self._col_widths)
        page.draw_rect(
            fitz.Rect(self.MARGIN, y, self.MARGIN + total_w, y + self.ROW_H),
            color=None, fill=bg,
        )
        for col, w in zip(self.columns, self._col_widths):
            raw = row.get(col, "")
            text = _fmt(raw, col)
            align = fitz.TEXT_ALIGN_RIGHT if _is_numeric_col(col) else fitz.TEXT_ALIGN_LEFT
            # Pick colour for numeric values
            text_color = _DARK
            if _is_numeric_col(col):
                try:
                    fval = float(raw)
                    if "debit" in col.lower():
                        if fval > 0:
                            text_color = _NEG
                        elif fval < 0:
                            text_color = _POS
                    else:
                        if fval > 0:
                            text_color = _POS
                        elif fval < 0:
                            text_color = _NEG
                except (ValueError, TypeError):
                    pass
            page.insert_textbox(
                fitz.Rect(x + 4, y + 2, x + w - 4, y + self.ROW_H),
                text,
                fontsize=7,
                fontname="helv",
                color=text_color,
                align=align,
            )
            x += w
        # Row bottom border
        page.draw_line(
            fitz.Point(self.MARGIN, y + self.ROW_H),
            fitz.Point(self.MARGIN + total_w, y + self.ROW_H),
            color=_BORDER, width=0.3,
        )

    # ------------------------------------------------------------------
    def _build(self) -> None:
        if not self.rows:
            page = self._new_page()
            page.insert_textbox(
                fitz.Rect(self.MARGIN, self.HEADER_H + 20, self.PAGE_W - self.MARGIN, self.HEADER_H + 60),
                "No records found for this report.",
                fontsize=11,
                fontname="helv",
                color=_MUTED,
                align=fitz.TEXT_ALIGN_CENTER,
            )
            return

        usable_bottom = self.PAGE_H - self.FOOTER_H - 4
        y_start = self.HEADER_H + 6

        page = self._new_page()
        self._draw_col_header(page, y_start)
        y = y_start + self.COL_HDR_H

        for idx, row in enumerate(self.rows):
            if y + self.ROW_H > usable_bottom:
                # New page
                page = self._new_page()
                self._draw_col_header(page, y_start)
                y = y_start + self.COL_HDR_H

            self._draw_row(page, row, y, even=idx % 2 == 0)
            y += self.ROW_H

    # ------------------------------------------------------------------
    def save(self, path: Path) -> None:
        self.doc.save(str(path))
        self.doc.close()


# ---------------------------------------------------------------------------
# Excel helper
# ---------------------------------------------------------------------------

_THIN = Side(style="thin", color="CBD5E1")
_THICK_ACCENT = Side(style="medium", color="3B82F6")


def _xl_border(top=None, bottom=None, left=None, right=None) -> Border:
    return Border(top=top, bottom=bottom, left=left, right=right)


# ---------------------------------------------------------------------------
# ReportExporter
# ---------------------------------------------------------------------------

class ReportExporter:
    def build(self, db: Session, report_kind: str, financial_year: str, output_format: str) -> Path:
        rows, title = self._data(db, report_kind, financial_year)
        output_format = output_format.lower()
        settings = get_settings()
        safe_kind = report_kind.replace("_", "-")
        path = settings.export_dir / f"{safe_kind}-{financial_year.replace(' ', '-').lower()}-{uuid.uuid4().hex[:8]}.{output_format}"
        if output_format == "csv":
            pd.DataFrame(rows).to_csv(path, index=False)
        elif output_format in {"xlsx", "excel"}:
            path = path.with_suffix(".xlsx")
            self._write_excel(path, title, rows)
        elif output_format == "json":
            path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        elif output_format == "pdf":
            self._write_pdf(path, title, rows)
        else:
            raise ValueError("Supported formats are csv, xlsx, json and pdf")
        return path

    def _data(self, db: Session, report_kind: str, financial_year: str) -> tuple[list[dict[str, Any]], str]:
        tax_year = db.scalar(select(TaxYear).where(TaxYear.financial_year == financial_year))
        if not tax_year:
            raise ValueError("Unknown financial year")
        kind = report_kind.lower().replace("-", "_")
        if kind in {"income_summary", "tax_summary", "credit_summary"}:
            dashboard = summary_service.dashboard(db, financial_year)
            if kind == "tax_summary":
                comparison = dashboard["tax_comparison"]
                rows = [
                    {
                        "regime": "Readiness",
                        "status": dashboard["readiness"]["status"],
                        "unresolved_credits": dashboard["readiness"]["unresolved_credit_count"],
                        "warnings": "; ".join(dashboard["readiness"]["warnings"]),
                    },
                    {"regime": "Old", **comparison["old"]},
                    {"regime": "New", **comparison["new"]},
                    {"regime": "Recommendation", "recommended": comparison["recommended"], "estimated_savings": comparison["estimated_savings"]},
                ]
            elif kind == "credit_summary":
                rows = dashboard["category_breakdown"]
            else:
                rows = [{"metric": key, "amount": value} for key, value in dashboard["metrics"].items()]
            return rows, kind.replace("_", " ").title()
        if kind == "bank_wise_summary":
            data = db.execute(
                select(
                    Transaction.bank_name,
                    func.sum(Transaction.credit),
                    func.sum(Transaction.debit),
                    func.count(Transaction.id),
                )
                .where(Transaction.tax_year_id == tax_year.id)
                .group_by(Transaction.bank_name)
            ).all()
            return [
                {"bank": bank or "Unknown", "credits": float(credits or 0), "debits": float(debits or 0), "transactions": count}
                for bank, credits, debits, count in data
            ], "Bank-wise Summary"
        if kind == "interest_summary":
            items = db.scalars(select(Interest).where(Interest.tax_year_id == tax_year.id)).all()
            return [
                {"type": item.interest_type, "payer": item.payer, "amount": float(item.amount), "tds": float(item.tds)} for item in items
            ], "Interest Summary"
        if kind == "dividend_summary":
            items = db.scalars(select(Dividend).where(Dividend.tax_year_id == tax_year.id)).all()
            return [
                {"company_or_fund": item.company_or_fund, "amount": float(item.amount), "tds": float(item.tds)} for item in items
            ], "Dividend Summary"
        if kind == "capital_gain_report":
            items = db.scalars(select(CapitalGain).where(CapitalGain.tax_year_id == tax_year.id)).all()
            return [
                {
                    "asset_type": item.asset_type,
                    "symbol_or_folio": item.symbol_or_folio,
                    "purchase_date": item.purchase_date,
                    "sale_date": item.sale_date,
                    "quantity": float(item.quantity or 0),
                    "sale_value": float(item.sale_value),
                    "cost_value": float(item.cost_value),
                    "gain_type": item.gain_type,
                    "gain_amount": float(item.gain_amount),
                }
                for item in items
            ], "Capital Gain Report"
        if kind == "deduction_report":
            items = db.scalars(select(Deduction).where(Deduction.tax_year_id == tax_year.id)).all()
            return [
                {
                    "section": item.section,
                    "description": item.description,
                    "claimed": float(item.amount_claimed),
                    "eligible": float(item.amount_eligible),
                    "suggested": item.suggested,
                    "accepted": item.accepted,
                }
                for item in items
            ], "Deduction Report"
        if kind in {"ais_reconciliation", "26as_reconciliation"}:
            source = "AIS" if kind.startswith("ais") else "Form 26AS"
            report = reconciliation_service.report(db, financial_year, source)
            return report["items"], f"{source} Reconciliation"
        if kind == "review_items":
            txs = db.scalars(
                select(Transaction).where(
                    Transaction.tax_year_id == tax_year.id,
                    Transaction.needs_review.is_(True),
                    Transaction.review_status == "pending",
                )
            ).all()
            return self._transaction_rows(txs), "Review Items"
        income_type_map = {
            "salary_report": "Salary Income",
            "rental_report": "Rental Income",
            "business_report": "Business Income",
        }
        if kind in income_type_map:
            txs = db.scalars(
                select(Transaction).where(
                    Transaction.tax_year_id == tax_year.id,
                    Transaction.income_type == income_type_map[kind],
                )
            ).all()
            return self._transaction_rows(txs), kind.replace("_", " ").title()
        if kind == "expense_report":
            items = db.scalars(select(Expense).where(Expense.tax_year_id == tax_year.id)).all()
            return [
                {
                    "transaction_id": item.transaction_id,
                    "category": item.category,
                    "amount": float(item.amount),
                    "business_use_percent": float(item.business_use_percent),
                    "deductible": item.deductible,
                }
                for item in items
            ], "Expense Report"
        txs = db.scalars(select(Transaction).where(Transaction.tax_year_id == tax_year.id)).all()
        return self._transaction_rows(txs), "Transactions"

    @staticmethod
    def _transaction_rows(items: list[Transaction]) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "date": item.transaction_date,
                "description": item.description,
                "debit": float(item.debit),
                "credit": float(item.credit),
                "category": item.category,
                "income_type": item.income_type,
                "taxable": item.taxable,
                "exempt": item.exempt,
                "ignored": item.ignored,
                "duplicate": item.is_duplicate,
                "self_transfer": item.is_self_transfer,
                "confidence": float(item.confidence or 0),
            }
            for item in items
        ]

    # ------------------------------------------------------------------
    # Excel exporter (premium redesign)
    # ------------------------------------------------------------------
    @staticmethod
    def _write_excel(path: Path, title: str, rows: list[dict[str, Any]]) -> None:
        frame = pd.DataFrame(rows)
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="Report", index=False, startrow=3)
            sheet = writer.book["Report"]

            # ---- Title row (row 1) ----
            sheet.row_dimensions[1].height = 32
            title_cell = sheet["A1"]
            title_cell.value = title
            title_cell.font = Font(name="Calibri", bold=True, size=18, color="0F172A")
            title_cell.alignment = Alignment(horizontal="left", vertical="center")

            # ---- Subtitle row (row 2) ----
            sheet.row_dimensions[2].height = 16
            sub_cell = sheet["A2"]
            sub_cell.value = f"Generated on {datetime.now().strftime('%d %B %Y  %H:%M')}   |   {len(rows)} records   |   Local ITR Preparation"
            sub_cell.font = Font(name="Calibri", size=9, color="64748B", italic=True)
            sub_cell.alignment = Alignment(horizontal="left", vertical="center")

            # ---- Blank separator (row 3) ----
            sheet.row_dimensions[3].height = 6

            if not frame.empty:
                num_cols = frame.columns.size

                # Merge title across all columns
                if num_cols > 1:
                    last_col = get_column_letter(num_cols)
                    sheet.merge_cells(f"A1:{last_col}1")
                    sheet.merge_cells(f"A2:{last_col}2")

                # ---- Column header row (row 4) ----
                sheet.row_dimensions[4].height = 22
                header_fill = PatternFill("solid", fgColor="1E293B")
                accent_bottom = _xl_border(bottom=Side(style="medium", color="3B82F6"))
                for col_idx, col in enumerate(frame.columns, start=1):
                    cell = sheet.cell(row=4, column=col_idx)
                    cell.font = Font(name="Calibri", bold=True, size=10, color="FFFFFF")
                    cell.fill = header_fill
                    cell.alignment = Alignment(
                        horizontal="right" if _is_numeric_col(col) else "left",
                        vertical="center",
                    )
                    cell.border = accent_bottom

                # ---- Data rows ----
                even_fill = PatternFill("solid", fgColor="F1F5F9")
                odd_fill = PatternFill("solid", fgColor="FFFFFF")
                thin_border = _xl_border(bottom=_THIN)
                pos_font_color = "059669"
                neg_font_color = "DC2626"

                for row_idx, df_row in enumerate(frame.itertuples(index=False), start=5):
                    sheet.row_dimensions[row_idx].height = 15
                    fill = even_fill if (row_idx % 2 == 1) else odd_fill
                    for col_idx, (col, raw_val) in enumerate(zip(frame.columns, df_row), start=1):
                        cell = sheet.cell(row=row_idx, column=col_idx)
                        cell.fill = fill
                        cell.border = thin_border
                        is_num = _is_numeric_col(col)
                        if is_num:
                            try:
                                fval = float(raw_val)
                                cell.value = fval
                                cell.number_format = "#,##0.00"
                                cell.alignment = Alignment(horizontal="right", vertical="center")
                                if "debit" in col.lower():
                                    fnt_color = neg_font_color if fval > 0 else (pos_font_color if fval < 0 else "0F172A")
                                else:
                                    fnt_color = pos_font_color if fval > 0 else (neg_font_color if fval < 0 else "0F172A")
                                cell.font = Font(name="Calibri", size=9, color=fnt_color)
                            except (ValueError, TypeError):
                                cell.value = raw_val
                                cell.font = Font(name="Calibri", size=9, color="0F172A")
                                cell.alignment = Alignment(horizontal="left", vertical="center")
                        else:
                            cell.value = raw_val
                            cell.font = Font(name="Calibri", size=9, color="0F172A")
                            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

                # ---- Column widths ----
                for col_idx, col in enumerate(frame.columns, start=1):
                    col_letter = get_column_letter(col_idx)
                    header_len = len(col.replace("_", " ").title())
                    data_len = max(
                        (len(str(v)) for v in frame[col].head(300) if v is not None),
                        default=0,
                    )
                    width = min(48, max(header_len + 4, data_len + 2, 10))
                    sheet.column_dimensions[col_letter].width = width

                # ---- Freeze panes below header ----
                sheet.freeze_panes = "A5"

    # ------------------------------------------------------------------
    # PDF exporter (premium redesign)
    # ------------------------------------------------------------------
    @staticmethod
    def _write_pdf(path: Path, title: str, rows: list[dict[str, Any]]) -> None:
        columns = list(rows[0].keys()) if rows else ["message"]
        display_rows = rows if rows else [{"message": "No records found for this report."}]
        writer = _PdfWriter(title, display_rows, columns)
        writer.save(path)


report_exporter = ReportExporter()
