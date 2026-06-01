# PROMPT: Add tests for the actual Brigade Bangalore item-level POS CSV shape and five-minute billing-window conversion rule.
# CHANGES MADE: Used a tiny fixture CSV instead of the private challenge file, and asserted invoice aggregation by NMV.

from pathlib import Path

from app.analytics import converted_visitors
from app.models import StoreEvent
from app.pos import load_pos_transactions


def test_load_pos_transactions_aggregates_item_rows(tmp_path: Path):
    csv_path = tmp_path / "pos.csv"
    csv_path.write_text(
        "order_id,invoice_number,invoice_type,order_date,order_time,store_id,NMV,total_amount\n"
        "1,INV1,sales,10-04-2026,16:55:36,ST1008,100,120\n"
        "1,INV1,sales,10-04-2026,16:55:36,ST1008,50,60\n"
        "2,INV2,return,10-04-2026,17:00:00,ST1008,25,25\n",
        encoding="utf-8",
    )

    transactions = load_pos_transactions(csv_path)

    assert len(transactions) == 1
    assert transactions[0].transaction_id == "INV1"
    assert transactions[0].basket_value_inr == 150


def test_pos_window_converts_billing_visitor(sample_events, tmp_path: Path):
    csv_path = tmp_path / "pos.csv"
    csv_path.write_text(
        "order_id,invoice_number,invoice_type,order_date,order_time,store_id,NMV,total_amount\n"
        "1,INV1,sales,10-04-2026,16:55:36,ST1008,100,120\n",
        encoding="utf-8",
    )
    transactions = load_pos_transactions(csv_path)
    events = [StoreEvent.model_validate(event) for event in sample_events]

    assert converted_visitors(events, transactions, "ST1008") == {"VIS_000001"}
