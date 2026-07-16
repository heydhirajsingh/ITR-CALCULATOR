"""FIFO capital-gain computation for normalized investment buy/sell records."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models.entities import CapitalGain, Investment, TaxYear


@dataclass(slots=True)
class Lot:
    date: date
    quantity: Decimal
    unit_cost: Decimal


class CapitalGainsService:
    def calculate_fifo(self, db: Session, tax_year: TaxYear) -> int:
        investments = db.scalars(
            select(Investment)
            .where(Investment.transaction_date <= tax_year.ends_on)
            .order_by(Investment.symbol_or_folio, Investment.transaction_date, Investment.id)
        ).all()
        db.execute(delete(CapitalGain).where(CapitalGain.tax_year_id == tax_year.id))
        lots: dict[str, deque[Lot]] = defaultdict(deque)
        created = 0
        for item in investments:
            symbol = item.symbol_or_folio or f"UNKNOWN-{item.id}"
            quantity = Decimal(item.quantity or 0)
            if quantity <= 0:
                continue
            if item.transaction_kind.lower() == "buy":
                lots[symbol].append(Lot(item.transaction_date, quantity, Decimal(item.amount) / quantity))
                continue
            if item.transaction_kind.lower() != "sell" or not (tax_year.starts_on <= item.transaction_date <= tax_year.ends_on):
                continue
            remaining = quantity
            sale_unit = Decimal(item.amount) / quantity
            while remaining > 0 and lots[symbol]:
                lot = lots[symbol][0]
                matched = min(remaining, lot.quantity)
                cost = matched * lot.unit_cost
                sale = matched * sale_unit
                holding_days = (item.transaction_date - lot.date).days
                asset = item.instrument_type.lower()
                threshold = 365 if any(token in asset for token in ("equity", "mutual fund", "stock")) else 730
                gain_type = "LTCG" if holding_days > threshold else "STCG"
                db.add(
                    CapitalGain(
                        tax_year_id=tax_year.id,
                        asset_type=item.instrument_type,
                        symbol_or_folio=item.symbol_or_folio,
                        purchase_date=lot.date,
                        sale_date=item.transaction_date,
                        quantity=matched,
                        sale_value=sale,
                        cost_value=cost,
                        indexed_cost=None,
                        gain_type=gain_type,
                        gain_amount=sale - cost,
                        calculation_method="FIFO",
                    )
                )
                created += 1
                lot.quantity -= matched
                remaining -= matched
                if lot.quantity <= 0:
                    lots[symbol].popleft()
        db.commit()
        return created
