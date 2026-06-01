from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Transaction:
    store_id: str
    transaction_id: str
    timestamp: datetime
    basket_value_inr: float


def parse_pos_timestamp(date_value: str, time_value: str) -> datetime:
    parsed = datetime.strptime(f"{date_value} {time_value}", "%d-%m-%Y %H:%M:%S")
    return parsed.replace(tzinfo=UTC)


def load_pos_transactions(path: str | Path) -> list[Transaction]:
    invoice_totals: dict[tuple[str, str, datetime], float] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("invoice_type", "").lower() != "sales":
                continue
            store_id = row["store_id"]
            invoice = row["invoice_number"] or row["order_id"]
            timestamp = parse_pos_timestamp(row["order_date"], row["order_time"])
            amount = float(row.get("NMV") or row.get("total_amount") or 0)
            key = (store_id, invoice, timestamp)
            invoice_totals[key] = invoice_totals.get(key, 0.0) + amount

    return [
        Transaction(store_id=store_id, transaction_id=invoice, timestamp=timestamp, basket_value_inr=round(amount, 2))
        for (store_id, invoice, timestamp), amount in sorted(invoice_totals.items(), key=lambda item: item[0][2])
    ]


@lru_cache(maxsize=4)
def configured_transactions() -> tuple[Transaction, ...]:
    path = os.getenv("POS_CSV_PATH", "data/pos_transactions.csv")
    if not Path(path).exists():
        return ()
    return tuple(load_pos_transactions(path))
