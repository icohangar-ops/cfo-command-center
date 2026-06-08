"""
CFO Command Center — Data Sync Worker

Imports external financial data into Notion databases.
Supports CSV import, JSON API ingestion, and ERP sync patterns.

Usage:
    python -m src.workers.data_sync_worker --source csv --file vendors.csv --target vendor_scorecard
    python -m src.workers.data_sync_worker --source json --file cashflow.json --target cash_flow_forecast
"""

import json
import csv
import logging
import argparse
from datetime import datetime
from typing import Optional
from pathlib import Path

from ..config import (
    NOTION_TOKEN, DB_VENDOR_SCORECARD, DB_CASH_FLOW_FORECAST,
    DB_WORKING_CAPITAL, DB_AP_AR_AGING, DB_PAYMENT_OPTIMIZATION
)
from ..notion_client import NotionClient, to_rich_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("data_sync_worker")


# ── Field Mappings ──────────────────────────────────────────────────────

FIELD_MAPPINGS = {
    "vendor_scorecard": {
        "database_id": DB_VENDOR_SCORECARD,
        "title_field": "Vendor Name",
        "mappings": {
            "vendor_name": "Vendor Name",
            "vendor_id": "Vendor ID",
            "category": "Category",
            "payment_terms": "Payment Terms",
            "early_pay_discount": "Early Pay Discount",
            "annual_spend": "Annual Spend",
            "risk_rating": "Risk Rating",
            "on_time_delivery": "On-Time Delivery",
            "quality_score": "Quality Score",
            "strategic_priority": "Strategic Priority",
            "status": "Status",
            "contract_end_date": "Contract End Date",
            "notes": "Notes",
        },
        "number_fields": {"annual_spend", "on_time_delivery"},
        "date_fields": {"contract_end_date"},
        "percent_fields": {"on_time_delivery"},
    },
    "cash_flow_forecast": {
        "database_id": DB_CASH_FLOW_FORECAST,
        "title_field": "Week",
        "mappings": {
            "week": "Week",
            "opening_balance": "Opening Balance",
            "cash_inflows": "Cash Inflows",
            "cash_outflows": "Cash Outflows",
            "ar_collections": "AR Collections",
            "ap_payments": "AP Payments",
            "payroll": "Payroll",
            "capex": "CapEx",
            "other_inflows": "Other Inflows",
            "other_outflows": "Other Outflows",
            "variance_vs_forecast": "Variance vs Forecast",
            "variance_pct": "Variance Pct",
            "confidence_level": "Confidence Level",
            "week_status": "Week Status",
            "notes": "Notes",
        },
        "number_fields": {
            "opening_balance", "cash_inflows", "cash_outflows",
            "ar_collections", "ap_payments", "payroll", "capex",
            "other_inflows", "other_outflows", "variance_vs_forecast", "variance_pct"
        },
        "select_fields": {"confidence_level", "week_status"},
    },
    "working_capital": {
        "database_id": DB_WORKING_CAPITAL,
        "title_field": "Period",
        "mappings": {
            "period": "Period",
            "dso": "DSO (Days Sales Outstanding)",
            "dpo": "DPO (Days Payable Outstanding)",
            "dio": "DIO (Days Inventory Outstanding)",
            "current_ratio": "Current Ratio",
            "quick_ratio": "Quick Ratio",
            "net_working_capital": "Net Working Capital",
            "revenue_mtd": "Revenue (MTD)",
            "ar_balance": "AR Balance",
            "ap_balance": "AP Balance",
            "inventory_value": "Inventory Value",
            "short_term_debt": "Short-Term Debt",
            "cash_position": "Cash Position",
            "ccc_trend": "CCC Trend",
            "notes": "Notes",
        },
        "number_fields": {
            "dso", "dpo", "dio", "current_ratio", "quick_ratio",
            "net_working_capital", "revenue_mtd", "ar_balance", "ap_balance",
            "inventory_value", "short_term_debt", "cash_position"
        },
        "select_fields": {"ccc_trend"},
    },
    "ap_ar_aging": {
        "database_id": DB_AP_AR_AGING,
        "title_field": "Entry",
        "mappings": {
            "entry": "Entry",
            "type": "Type",
            "entity": "Entity",
            "invoice_number": "Invoice #",
            "invoice_date": "Invoice Date",
            "due_date": "Due Date",
            "original_amount": "Original Amount",
            "outstanding_balance": "Outstanding Balance",
            "aging_bucket": "Aging Bucket",
            "priority": "Priority",
            "status": "Status",
            "action_required": "Action Required",
            "notes": "Notes",
        },
        "number_fields": {"original_amount", "outstanding_balance"},
        "date_fields": {"invoice_date", "due_date"},
        "select_fields": {"type", "aging_bucket", "priority", "status"},
    },
    "payment_optimization": {
        "database_id": DB_PAYMENT_OPTIMIZATION,
        "title_field": "Payment",
        "mappings": {
            "payment": "Payment",
            "vendor": "Vendor",
            "invoice_amount": "Invoice Amount",
            "due_date": "Due Date",
            "early_pay_deadline": "Early Pay Deadline",
            "discount_available": "Discount Available",
            "annualized_savings_rate": "Annualized Savings Rate",
            "borrowing_cost": "Borrowing Cost",
            "net_benefit": "Net Benefit",
            "ai_recommendation": "AI Recommendation",
            "priority_rank": "Priority Rank",
            "payment_status": "Payment Status",
            "payment_date": "Payment Date",
            "notes": "Notes",
        },
        "number_fields": {
            "invoice_amount", "annualized_savings_rate",
            "borrowing_cost", "net_benefit", "priority_rank"
        },
        "date_fields": {"due_date", "early_pay_deadline", "payment_date"},
        "select_fields": {
            "discount_available", "ai_recommendation", "payment_status"
        },
    },
}


class DataSyncWorker:
    """Imports external data into Notion databases."""

    def __init__(self, client: NotionClient):
        self.client = client

    def import_csv(self, file_path: str, target: str, dry_run: bool = False) -> dict:
        """
        Import a CSV file into a Notion database.

        Args:
            file_path: Path to CSV file
            target: Target database key (e.g., 'vendor_scorecard')
            dry_run: If True, validates but doesn't write to Notion
        """
        if target not in FIELD_MAPPINGS:
            return {"error": f"Unknown target: {target}. Available: {list(FIELD_MAPPINGS.keys())}"}

        schema = FIELD_MAPPINGS[target]
        rows = []
        errors = []

        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, 1):
                try:
                    properties = self._map_row(row, schema)
                    rows.append(properties)
                except Exception as e:
                    errors.append({"row": i, "error": str(e), "data": dict(row)})

        if dry_run:
            return {
                "status": "dry_run",
                "target": target,
                "rows_validated": len(rows),
                "errors": len(errors),
                "error_details": errors[:5],
            }

        # Write to Notion
        created = 0
        for props in rows:
            try:
                self.client.create_page(schema["database_id"], props)
                created += 1
            except Exception as e:
                errors.append({"error": str(e), "data": props})

        return {
            "status": "complete",
            "target": target,
            "rows_created": created,
            "errors": len(errors),
            "error_details": errors[:5],
        }

    def import_json(self, file_path: str, target: str, dry_run: bool = False) -> dict:
        """Import a JSON file (array of objects) into a Notion database."""
        if target not in FIELD_MAPPINGS:
            return {"error": f"Unknown target: {target}. Available: {list(FIELD_MAPPINGS.keys())}"}

        schema = FIELD_MAPPINGS[target]

        with open(file_path, "r") as f:
            data = json.load(f)

        if not isinstance(data, list):
            data = [data]

        rows = []
        errors = []
        for i, item in enumerate(data, 1):
            try:
                properties = self._map_row(item, schema)
                rows.append(properties)
            except Exception as e:
                errors.append({"row": i, "error": str(e), "data": item})

        if dry_run:
            return {
                "status": "dry_run",
                "target": target,
                "rows_validated": len(rows),
                "errors": len(errors),
                "error_details": errors[:5],
            }

        created = 0
        for props in rows:
            try:
                self.client.create_page(schema["database_id"], props)
                created += 1
            except Exception as e:
                errors.append({"error": str(e), "data": props})

        return {
            "status": "complete",
            "target": target,
            "rows_created": created,
            "errors": len(errors),
            "error_details": errors[:5],
        }

    def _map_row(self, row: dict, schema: dict) -> dict:
        """Map a source row to Notion property format using the schema."""
        properties = {}
        title_key = schema["title_field"]
        number_fields = schema.get("number_fields", set())
        date_fields = schema.get("date_fields", set())
        select_fields = schema.get("select_fields", set())
        percent_fields = schema.get("percent_fields", set())

        for source_key, notion_key in schema["mappings"].items():
            value = row.get(source_key)
            if value is None or value == "":
                continue

            # Convert string values
            if isinstance(value, str):
                value = value.strip()

            if notion_key == title_key:
                properties[notion_key] = {"title": to_rich_text(str(value))}
            elif source_key in percent_fields:
                num_val = self._to_number(value)
                if num_val is not None:
                    if num_val > 1:  # e.g., 97 -> 0.97
                        num_val = num_val / 100.0
                    properties[notion_key] = {"number": num_val}
            elif source_key in number_fields:
                num_val = self._to_number(value)
                if num_val is not None:
                    properties[notion_key] = {"number": num_val}
            elif source_key in date_fields:
                properties[notion_key] = {"date": {"start": str(value)}}
            elif source_key in select_fields:
                properties[notion_key] = {"select": {"name": str(value)}}
            else:
                properties[notion_key] = {"rich_text": to_rich_text(str(value))}

        if title_key not in properties:
            raise ValueError(f"Title field '{title_key}' not found in row")

        return properties

    def _to_number(self, value) -> Optional[float]:
        """Convert a value to a float, handling currency formats."""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace("$", "").replace(",", "").replace("%", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None


# ── CLI ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CFO Command Center — Data Sync Worker")
    parser.add_argument("--source", choices=["csv", "json"], required=True)
    parser.add_argument("--file", required=True, help="Path to source file")
    parser.add_argument("--target", required=True,
                        choices=list(FIELD_MAPPINGS.keys()),
                        help="Target Notion database")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate without writing to Notion")
    args = parser.parse_args()

    client = NotionClient(token=NOTION_TOKEN)
    worker = DataSyncWorker(client)

    if args.source == "csv":
        result = worker.import_csv(args.file, args.target, dry_run=args.dry_run)
    else:
        result = worker.import_json(args.file, args.target, dry_run=args.dry_run)

    print(json.dumps(result, indent=2))
