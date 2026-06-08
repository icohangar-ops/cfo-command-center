"""
CFO Command Center — Agent Tools Registry

Defines all AI tools that can be invoked from within Notion's
built-in AI or via the MCP protocol. Each tool has a schema,
handler, and write-back capability to Notion databases.

These tools enable natural language queries like:
  "What's our cash position?" 
  "Which vendors are at risk?"
  "Should we pay Acme Steel early?"
  "What's the CCC trend?"
"""

import json
import logging
from typing import Any, Optional, Callable
from datetime import datetime

from ..notion_client import (
    NotionClient, get_title, get_number, get_select,
    get_date, to_rich_text, today_str
)
from ..config import (
    DB_VENDOR_SCORECARD, DB_CASH_FLOW_FORECAST, DB_WORKING_CAPITAL,
    DB_AP_AR_AGING, DB_PAYMENT_OPTIMIZATION, PAGE_CFO_CENTER,
    BORROWING_RATE_ANNUAL, BORROWING_RATE_DAILY
)

logger = logging.getLogger("agent_tools")


# ── Tool Schema Definitions ─────────────────────────────────────────────

TOOL_DEFINITIONS = {
    "get_cash_position": {
        "name": "get_cash_position",
        "description": "Get the current cash position and working capital metrics from the most recent period. Returns cash on hand, CCC, DSO, DPO, DIO, current ratio, and trend direction.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "get_vendor_risk_summary": {
        "name": "get_vendor_risk_summary",
        "description": "Get a summary of all vendors with their risk ratings, annual spend, on-time delivery %, quality scores, and strategic tier. Optionally filter by risk level.",
        "parameters": {
            "type": "object",
            "properties": {
                "risk_level": {
                    "type": "string",
                    "enum": ["Low", "Medium", "High", "Critical"],
                    "description": "Filter vendors by risk level. Omit for all vendors.",
                },
            },
            "required": [],
        },
    },
    "get_cash_flow_forecast": {
        "name": "get_cash_flow_forecast",
        "description": "Get the 13-week cash flow forecast. Returns weekly inflows, outflows, net cash flow, and closing balance. Identifies weeks with potential cash shortfalls.",
        "parameters": {
            "type": "object",
            "properties": {
                "weeks": {
                    "type": "integer",
                    "description": "Number of weeks to return (default: 13, max: 13)",
                    "default": 13,
                },
            },
            "required": [],
        },
    },
    "evaluate_early_payment": {
        "name": "evaluate_early_payment",
        "description": "Evaluate whether to pay a specific vendor early to capture a discount. Compares discount savings against the cost of borrowing to fund the early payment. Returns the net benefit and a recommendation.",
        "parameters": {
            "type": "object",
            "properties": {
                "vendor_name": {
                    "type": "string",
                    "description": "Name of the vendor to evaluate.",
                },
                "invoice_amount": {
                    "type": "number",
                    "description": "Invoice amount in dollars.",
                },
                "discount_terms": {
                    "type": "string",
                    "description": "Discount terms, e.g. '2/10 Net 30' meaning 2% discount if paid within 10 days of a Net 30 invoice.",
                },
                "days_to_due_date": {
                    "type": "integer",
                    "description": "Number of days until the invoice is due.",
                },
            },
            "required": ["vendor_name", "invoice_amount", "discount_terms", "days_to_due_date"],
        },
    },
    "get_ap_ar_summary": {
        "name": "get_ap_ar_summary",
        "description": "Get a summary of accounts payable and receivable. Returns totals by aging bucket (Current, 1-30, 31-60, 61-90, 90+ days), overdue items, and disputed items.",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["AP", "AR", "all"],
                    "description": "Filter by type: AP (payables), AR (receivables), or all (default: all).",
                },
            },
            "required": [],
        },
    },
    "get_payment_queue": {
        "name": "get_payment_queue",
        "description": "Get the AI-ranked payment optimization queue. Returns all queued payments sorted by priority rank, with discount savings, net benefit, and AI recommendations.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["Queued", "Approved", "Processing", "Completed", "all"],
                    "description": "Filter by payment status (default: Queued).",
                },
            },
            "required": [],
        },
    },
    "create_vendor_alert": {
        "name": "create_vendor_alert",
        "description": "Create a new vendor alert or note in the AP/AR Aging database. Use this to flag issues, add context, or record follow-up actions.",
        "parameters": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "Vendor or client name.",
                },
                "invoice_number": {
                    "type": "string",
                    "description": "Related invoice number.",
                },
                "amount": {
                    "type": "number",
                    "description": "Amount in dollars.",
                },
                "type": {
                    "type": "string",
                    "enum": ["Accounts Receivable", "Accounts Payable"],
                    "description": "Whether this is an AR or AP entry.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["Urgent", "High", "Normal", "Low"],
                    "description": "Priority level.",
                },
                "notes": {
                    "type": "string",
                    "description": "Description of the alert or action required.",
                },
            },
            "required": ["entity", "type", "notes"],
        },
    },
    "get_working_capital_history": {
        "name": "get_working_capital_history",
        "description": "Get historical working capital metrics over multiple periods. Shows DSO, DPO, DIO, CCC trends, cash position, and current ratio changes over time.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


class ToolRegistry:
    """Registry and dispatcher for all CFO Agent Tools."""

    def __init__(self, client: NotionClient):
        self.client = client
        self._handlers: dict[str, Callable] = {
            "get_cash_position": self._get_cash_position,
            "get_vendor_risk_summary": self._get_vendor_risk_summary,
            "get_cash_flow_forecast": self._get_cash_flow_forecast,
            "evaluate_early_payment": self._evaluate_early_payment,
            "get_ap_ar_summary": self._get_ap_ar_summary,
            "get_payment_queue": self._get_payment_queue,
            "create_vendor_alert": self._create_vendor_alert,
            "get_working_capital_history": self._get_working_capital_history,
        }

    def list_tools(self) -> list[dict]:
        """Return all tool definitions (for MCP/Agent Tools registration)."""
        return list(TOOL_DEFINITIONS.values())

    def invoke(self, tool_name: str, arguments: dict = None) -> dict:
        """Invoke a tool by name with arguments. Returns result dict."""
        if tool_name not in self._handlers:
            return {"error": f"Unknown tool: {tool_name}", "available": list(self._handlers.keys())}

        handler = self._handlers[tool_name]
        args = arguments or {}

        try:
            logger.info(f"Invoking tool: {tool_name} with args: {json.dumps(args)[:200]}")
            result = handler(args)
            logger.info(f"Tool {tool_name} completed successfully")
            return result
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return {"error": str(e), "tool": tool_name}

    # ── Tool Handlers ───────────────────────────────────────────────────

    def _get_cash_position(self, args: dict) -> dict:
        """Return the latest working capital metrics."""
        results = self.client.query_database(
            DB_WORKING_CAPITAL,
            sorts=[{"property": "Period", "direction": "descending"}],
            page_size=1,
        )
        if not results:
            return {"error": "No working capital data available"}

        props = results[0]["properties"]
        dso = get_number(props, "DSO (Days Sales Outstanding)") or 0
        dpo = get_number(props, "DPO (Days Payable Outstanding)") or 0
        dio = get_number(props, "DIO (Days Inventory Outstanding)") or 0

        return {
            "period": get_title(props, "Period"),
            "cash_position": get_number(props, "Cash Position") or 0,
            "net_working_capital": get_number(props, "Net Working Capital") or 0,
            "current_ratio": get_number(props, "Current Ratio") or 0,
            "quick_ratio": get_number(props, "Quick Ratio") or 0,
            "dso": dso,
            "dpo": dpo,
            "dio": dio,
            "ccc": dso + dio - dpo,
            "trend": get_select(props, "CCC Trend") or "Unknown",
            "revenue_mtd": get_number(props, "Revenue (MTD)") or 0,
            "ar_balance": get_number(props, "AR Balance") or 0,
            "ap_balance": get_number(props, "AP Balance") or 0,
            "short_term_debt": get_number(props, "Short-Term Debt") or 0,
            "ai_recommendation": get_title(props, "AI Recommendation"),
        }

    def _get_vendor_risk_summary(self, args: dict) -> dict:
        """Return vendor risk summary, optionally filtered by risk level."""
        filter_obj = None
        if args.get("risk_level"):
            filter_obj = {"property": "Risk Rating", "select": {"equals": args["risk_level"]}}

        results = self.client.query_database(DB_VENDOR_SCORECARD, filter_obj=filter_obj)
        vendors = []
        for v in results:
            props = v["properties"]
            vendors.append({
                "name": get_title(props, "Vendor Name"),
                "category": get_select(props, "Category"),
                "annual_spend": get_number(props, "Annual Spend") or 0,
                "risk_rating": get_select(props, "Risk Rating"),
                "on_time_delivery": get_number(props, "On-Time Delivery") or 0,
                "quality_score": get_select(props, "Quality Score"),
                "strategic_priority": get_select(props, "Strategic Priority"),
                "status": get_select(props, "Status"),
                "contract_end": get_date(props, "Contract End Date"),
            })

        total_spend = sum(v["annual_spend"] for v in vendors)
        risk_breakdown = {}
        for v in vendors:
            r = v["risk_rating"] or "Unknown"
            risk_breakdown[r] = risk_breakdown.get(r, 0) + 1

        return {
            "total_vendors": len(vendors),
            "total_annual_spend": total_spend,
            "risk_breakdown": risk_breakdown,
            "vendors": vendors,
        }

    def _get_cash_flow_forecast(self, args: dict) -> dict:
        """Return the N-week cash flow forecast."""
        weeks = min(args.get("weeks", 13), 13)
        results = self.client.query_database(
            DB_CASH_FLOW_FORECAST,
            sorts=[{"property": "Week", "direction": "ascending"}],
            page_size=weeks,
        )
        forecast = []
        min_closing = float("inf")
        min_week = ""

        for w in results:
            props = w["properties"]
            opening = get_number(props, "Opening Balance") or 0
            inflows = get_number(props, "Cash Inflows") or 0
            outflows = get_number(props, "Cash Outflows") or 0
            closing = opening + inflows - outflows

            if closing < min_closing:
                min_closing = closing
                min_week = get_title(props, "Week")

            forecast.append({
                "week": get_title(props, "Week"),
                "opening_balance": opening,
                "cash_inflows": inflows,
                "cash_outflows": outflows,
                "net_cash_flow": inflows - outflows,
                "closing_balance": closing,
                "confidence": get_select(props, "Confidence Level"),
                "status": get_select(props, "Week Status"),
            })

        return {
            "forecast": forecast,
            "min_closing_balance": min_closing,
            "min_closing_week": min_week,
            "total_inflows": sum(f["cash_inflows"] for f in forecast),
            "total_outflows": sum(f["cash_outflows"] for f in forecast),
            "net_position": sum(f["net_cash_flow"] for f in forecast),
        }

    def _evaluate_early_payment(self, args: dict) -> dict:
        """Evaluate whether to pay early for a discount."""
        vendor = args["vendor_name"]
        amount = args["invoice_amount"]
        discount_str = args["discount_terms"]
        days_to_due = args["days_to_due_date"]

        # Parse discount terms
        try:
            parts = discount_str.split("/")
            discount_rate = float(parts[0]) / 100.0
            discount_days = int(parts[1].split()[0])
        except (ValueError, IndexError):
            return {"error": f"Cannot parse discount terms: {discount_str}. Use format like '2/10 Net 30'."}

        # Calculate
        if days_to_due <= discount_days:
            return {
                "vendor": vendor,
                "amount": amount,
                "recommendation": "No action needed",
                "reason": f"Discount deadline has already passed or is today ({days_to_due}d to due, discount window is {discount_days}d).",
                "discount_savings": 0,
                "net_benefit": 0,
            }

        days_early = days_to_due - discount_days
        discount_savings = amount * discount_rate
        borrow_cost = amount * BORROWING_RATE_DAILY * days_early
        net_benefit = discount_savings - borrow_cost

        if net_benefit > 0:
            recommendation = "PAY EARLY — Discount exceeds borrowing cost"
        elif net_benefit > -100:
            recommendation = "MARGINAL — Discount approximately equals borrowing cost"
        else:
            recommendation = "PAY ON DUE DATE — Borrowing cost exceeds discount"

        annualized_rate = (discount_rate / (1 - discount_rate)) * (365 / days_early) if days_early > 0 else 0

        return {
            "vendor": vendor,
            "invoice_amount": amount,
            "discount_terms": discount_str,
            "days_to_due_date": days_to_due,
            "discount_days_remaining": days_to_due - discount_days,
            "discount_savings": round(discount_savings, 2),
            "borrowing_cost": round(borrow_cost, 2),
            "net_benefit": round(net_benefit, 2),
            "annualized_rate_pct": round(annualized_rate * 100, 2),
            "recommendation": recommendation,
            "borrowing_rate_pct": BORROWING_RATE_ANNUAL * 100,
        }

    def _get_ap_ar_summary(self, args: dict) -> dict:
        """Return AP/AR summary by aging bucket."""
        filter_obj = None
        if args.get("type") and args["type"] != "all":
            type_name = {"AP": "Accounts Payable", "AR": "Accounts Receivable"}.get(args["type"], args["type"])
            filter_obj = {"property": "Type", "select": {"equals": type_name}}

        results = self.client.query_database(DB_AP_AR_AGING, filter_obj=filter_obj)

        buckets = {"Current": 0, "1-30 Days": 0, "31-60 Days": 0, "61-90 Days": 0, "90+ Days": 0}
        by_type = {"Accounts Receivable": {"total": 0, "count": 0}, "Accounts Payable": {"total": 0, "count": 0}}
        overdue_items = []
        disputed_items = []

        for item in results:
            props = item["properties"]
            balance = get_number(props, "Outstanding Balance") or 0
            bucket = get_select(props, "Aging Bucket") or "Current"
            item_type = get_select(props, "Type") or "Unknown"
            status = get_select(props, "Status") or "Open"
            priority = get_select(props, "Priority") or "Normal"

            if bucket in buckets:
                buckets[bucket] += balance

            if item_type in by_type:
                by_type[item_type]["total"] += balance
                by_type[item_type]["count"] += 1

            if status == "Overdue":
                overdue_items.append({
                    "entity": get_title(props, "Entry"),
                    "balance": balance,
                    "priority": priority,
                    "action": get_title(props, "Action Required"),
                })
            elif status == "Disputed":
                disputed_items.append({
                    "entity": get_title(props, "Entry"),
                    "balance": balance,
                    "action": get_title(props, "Action Required"),
                })

        return {
            "aging_buckets": buckets,
            "total_outstanding": sum(buckets.values()),
            "by_type": by_type,
            "overdue_count": len(overdue_items),
            "overdue_total": sum(i["balance"] for i in overdue_items),
            "overdue_items": overdue_items[:10],
            "disputed_count": len(disputed_items),
            "disputed_total": sum(i["balance"] for i in disputed_items),
            "disputed_items": disputed_items[:10],
        }

    def _get_payment_queue(self, args: dict) -> dict:
        """Return AI-ranked payment queue."""
        filter_obj = None
        if args.get("status") and args["status"] != "all":
            filter_obj = {"property": "Payment Status", "select": {"equals": args["status"]}}

        results = self.client.query_database(
            DB_PAYMENT_OPTIMIZATION,
            filter_obj=filter_obj,
            sorts=[{"property": "Priority Rank", "direction": "ascending"}],
        )

        payments = []
        total_savings = 0
        for p in results:
            props = p["properties"]
            net = get_number(props, "Net Benefit") or 0
            total_savings += max(0, net)
            payments.append({
                "rank": get_number(props, "Priority Rank") or 0,
                "vendor": get_title(props, "Payment"),
                "amount": get_number(props, "Invoice Amount") or 0,
                "due_date": get_date(props, "Due Date"),
                "discount": get_select(props, "Discount Available"),
                "annualized_savings_rate": get_number(props, "Annualized Savings Rate") or 0,
                "borrowing_cost": get_number(props, "Borrowing Cost") or 0,
                "net_benefit": net,
                "recommendation": get_select(props, "AI Recommendation"),
                "status": get_select(props, "Payment Status"),
            })

        return {
            "total_payments": len(payments),
            "total_potential_savings": total_savings,
            "payments": payments,
        }

    def _create_vendor_alert(self, args: dict) -> dict:
        """Create a new vendor alert in the AP/AR Aging database."""
        from datetime import datetime, timedelta

        today = datetime.utcnow()
        due_date = today + timedelta(days=30)

        entry_name = f"ALERT: {args['entity']}"
        properties = {
            "Entry": {"title": to_rich_text(entry_name)},
            "Type": {"select": {"name": args.get("type", "Accounts Payable")}},
            "Entity": {"rich_text": to_rich_text(args["entity"])},
            "Invoice #": {"rich_text": to_rich_text(args.get("invoice_number", "N/A"))},
            "Invoice Date": {"date": {"start": today.strftime("%Y-%m-%d")}},
            "Due Date": {"date": {"start": due_date.strftime("%Y-%m-%d")}},
            "Original Amount": {"number": args.get("amount", 0)},
            "Outstanding Balance": {"number": args.get("amount", 0)},
            "Aging Bucket": {"select": {"name": "Current"}},
            "Priority": {"select": {"name": args.get("priority", "Normal")}},
            "Status": {"select": {"name": "Open"}},
            "Action Required": {"rich_text": to_rich_text(args["notes"])},
        }

        page = self.client.create_page(DB_AP_AR_AGING, properties)
        return {
            "status": "created",
            "alert_id": page["id"],
            "entity": args["entity"],
            "message": f"Alert created for {args['entity']}: {args['notes'][:100]}",
        }

    def _get_working_capital_history(self, args: dict) -> dict:
        """Return historical working capital metrics."""
        results = self.client.query_database(
            DB_WORKING_CAPITAL,
            sorts=[{"property": "Period", "direction": "ascending"}],
        )

        history = []
        for w in results:
            props = w["properties"]
            dso = get_number(props, "DSO (Days Sales Outstanding)") or 0
            dpo = get_number(props, "DPO (Days Payable Outstanding)") or 0
            dio = get_number(props, "DIO (Days Inventory Outstanding)") or 0
            history.append({
                "period": get_title(props, "Period"),
                "dso": dso,
                "dpo": dpo,
                "dio": dio,
                "ccc": dso + dio - dpo,
                "current_ratio": get_number(props, "Current Ratio") or 0,
                "quick_ratio": get_number(props, "Quick Ratio") or 0,
                "cash_position": get_number(props, "Cash Position") or 0,
                "net_working_capital": get_number(props, "Net Working Capital") or 0,
                "revenue": get_number(props, "Revenue (MTD)") or 0,
                "trend": get_select(props, "CCC Trend"),
            })

        # Calculate trends
        if len(history) >= 2:
            latest = history[-1]
            previous = history[-2]
            trends = {
                "ccc_change": latest["ccc"] - previous["ccc"],
                "cash_change": latest["cash_position"] - previous["cash_position"],
                "nwc_change": latest["net_working_capital"] - previous["net_working_capital"],
            }
        else:
            trends = {}

        return {
            "periods": history,
            "latest": history[-1] if history else None,
            "trends": trends,
        }
