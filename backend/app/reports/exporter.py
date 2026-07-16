"""Local report generation in CSV, Excel, JSON and PDF formats."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
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

    @staticmethod
    def _write_excel(path: Path, title: str, rows: list[dict[str, Any]]) -> None:
        frame = pd.DataFrame(rows)
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="Report", index=False, startrow=2)
            sheet = writer.book["Report"]
            sheet["A1"] = title
            sheet["A1"].font = Font(bold=True, size=16)
            if frame.columns.size:
                header_fill = PatternFill("solid", fgColor="1F2937")
                for cell in sheet[3]:
                    cell.font = Font(bold=True, color="FFFFFF")
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal="center")
                for index, column in enumerate(frame.columns, start=1):
                    width = max(12, min(45, max(len(str(column)), *(len(str(value)) for value in frame[column].head(200)))))
                    sheet.column_dimensions[chr(64 + index) if index <= 26 else "A"].width = width
            sheet.freeze_panes = "A4"

    @staticmethod
    def _write_pdf(path: Path, title: str, rows: list[dict[str, Any]]) -> None:
        document = fitz.open()
        page = document.new_page(width=842, height=595)
        y = 42
        page.insert_text((36, y), title, fontsize=18)
        y += 24
        page.insert_text((36, y), f"Generated locally on {datetime.now().strftime('%d %b %Y %H:%M')}", fontsize=9)
        y += 24
        columns = list(rows[0].keys()) if rows else ["message"]
        page.insert_text((36, y), " | ".join(columns[:8]), fontsize=8)
        y += 14
        for row in rows or [{"message": "No records"}]:
            line = " | ".join(str(row.get(column, ""))[:28] for column in columns[:8])
            if y > 560:
                page = document.new_page(width=842, height=595)
                y = 36
            page.insert_text((36, y), line, fontsize=7)
            y += 11
        document.save(path)
        document.close()


report_exporter = ReportExporter()
