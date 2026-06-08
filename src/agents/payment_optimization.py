"""
CFO Command Center — Payment Optimization Agent

Reads: Vendor Scorecard, Payment Optimization Queue, AP/AR Aging
Writes: Updated payment queue with AI rankings, net benefit analysis
Actions: Ranks payments by net benefit (discount - borrowing cost)
"""

import logging
from datetime import datetime, timedelta

from ..notion_client import (
    NotionClient, get_title, get_number, get_select, get_date,
    to_rich_text
)
from .. import config

logger = logging.getLogger("agent.payment_optimization")


class PaymentOptimizationAgent:
    """Ranks vendor payments by optimal payment timing to maximize savings."""

    def __init__(self, client: NotionClient):
        self.client = client
        self.queue_db = config.DB_PAYMENT_OPTIMIZATION
        self.vendor_db = config.DB_VENDOR_SCORECARD

    def run(self) -> dict:
        logger.info("=== Payment Optimization Agent START ===")
        vendors = self._load_vendors()
        queue = self._load_queue()

        if not queue:
            logger.warning("No payments in queue.")
            return {"status": "no_data"}

        analysis = self._analyze(queue, vendors)
        self._update_queue(analysis)
        self._write_summary(analysis)
        logger.info(
            f"Analysis complete: {analysis['total_discount_savings']:,.0f} in savings identified, "
            f"{analysis['payments_to_early_pay']} recommended for early payment"
        )
        logger.info("=== Payment Optimization Agent END ===")
        return analysis

    # ── Data Loading ────────────────────────────────────────────────────

    def _load_vendors(self) -> dict[str, dict]:
        results = self.client.query_database(self.vendor_db)
        vendor_map = {}
        for v in results:
            name = get_title(v["properties"], "Vendor Name")
            if name:
                vendor_map[name.lower()] = {
                    "page_id": v["id"],
                    "risk_rating": get_select(v["properties"], "Risk Rating"),
                    "strategic_priority": get_select(v["properties"], "Strategic Priority"),
                }
        return vendor_map

    def _load_queue(self) -> list[dict]:
        return self.client.query_database(
            self.queue_db,
            filter_obj={"property": "Payment Status", "select": {"equals": "Queued"}},
            sorts=[{"property": "Priority Rank", "direction": "ascending"}],
        )

    # ── Analysis ────────────────────────────────────────────────────────

    def _analyze(self, queue: list[dict], vendors: dict) -> dict:
        ranked_payments = []
        total_discount_savings = 0
        payments_to_early_pay = 0
        total_borrowing_cost = 0

        today = datetime.utcnow().date()

        for payment in queue:
            props = payment["properties"]
            vendor_name = get_title(props, "Payment")
            amount = get_number(props, "Invoice Amount") or 0
            due_date_str = get_date(props, "Due Date")
            discount_type = get_select(props, "Discount Available") or "None"

            # Parse dates
            due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date() if due_date_str else today
            days_to_due = (due_date - today).days

            # Calculate discount and borrowing cost
            discount_rate, discount_days = self._parse_discount(discount_type)

            if discount_rate > 0 and days_to_due > discount_days:
                # Opportunity exists: pay early to capture discount
                early_date = today + timedelta(days=discount_days)
                days_early = days_to_due - discount_days
                borrow_cost = amount * config.BORROWING_RATE_DAILY * days_early
                discount_savings = amount * discount_rate
                net_benefit = discount_savings - borrow_cost
                annualized_rate = (discount_rate / (1 - discount_rate)) * (365 / days_early) if days_early > 0 else 0

                recommendation = "Pay Early (Discount)" if net_benefit > 0 else "Pay on Due Date"
                if net_benefit > 0:
                    payments_to_early_pay += 1
                total_discount_savings += max(0, net_benefit)
                total_borrowing_cost += borrow_cost
            elif discount_rate > 0 and days_to_due <= discount_days:
                # Discount window still open or expired
                if days_to_due > 0:
                    discount_savings = amount * discount_rate
                    net_benefit = discount_savings
                    recommendation = "Pay Early (Discount)"
                    annualized_rate = 0.0
                    payments_to_early_pay += 1
                    total_discount_savings += discount_savings
                else:
                    discount_savings = 0
                    net_benefit = 0
                    recommendation = "Pay on Due Date"
                    annualized_rate = 0.0
            else:
                discount_savings = 0
                borrow_cost = 0
                net_benefit = 0
                annualized_rate = 0.0

                # No discount — determine if deferral is beneficial
                if days_to_due > 30:
                    recommendation = "Defer Payment"
                elif days_to_due < 0:
                    recommendation = "Pay on Due Date"
                else:
                    recommendation = "Negotiate Terms"

            # Check vendor risk for priority adjustment
            vendor_key = vendor_name.split(" - ")[0].lower() if vendor_name else ""
            vendor_info = vendors.get(vendor_key, {})
            risk = vendor_info.get("risk_rating", "Medium")
            tier = vendor_info.get("strategic_priority", "Tier 3 - Commodity")

            ranked_payments.append({
                "page_id": payment["id"],
                "vendor": vendor_name,
                "amount": amount,
                "due_date": due_date_str,
                "discount_type": discount_type,
                "discount_savings": discount_savings,
                "borrowing_cost": borrow_cost,
                "net_benefit": net_benefit,
                "annualized_rate": annualized_rate,
                "recommendation": recommendation,
                "risk_rating": risk,
                "strategic_tier": tier,
                "days_to_due": days_to_due,
            })

        # Sort by net benefit descending (highest savings first)
        ranked_payments.sort(key=lambda x: x["net_benefit"], reverse=True)

        # Assign priority ranks
        for i, p in enumerate(ranked_payments, 1):
            p["priority_rank"] = i

        return {
            "ranked_payments": ranked_payments,
            "total_discount_savings": total_discount_savings,
            "payments_to_early_pay": payments_to_early_pay,
            "total_borrowing_cost": total_borrowing_cost,
            "total_payments": len(queue),
        }

    def _parse_discount(self, discount_type: str) -> tuple[float, int]:
        """Parse discount notation like '2/10 Net 30' into (rate, days)."""
        if not discount_type or discount_type == "None":
            return 0.0, 0
        try:
            parts = discount_type.split("/")
            rate = float(parts[0]) / 100.0
            days = int(parts[1].split()[0])
            return rate, days
        except (ValueError, IndexError):
            return 0.0, 0

    # ── Write Back ──────────────────────────────────────────────────────

    def _update_queue(self, analysis: dict):
        """Update each payment row with AI analysis."""
        for p in analysis["ranked_payments"]:
            self.client.update_page(p["page_id"], {
                "AI Recommendation": {"select": {"name": p["recommendation"]}},
                "Priority Rank": {"number": p["priority_rank"]},
                "Annualized Savings Rate": {"number": round(p["annualized_rate"], 4)},
                "Borrowing Cost": {"number": round(p["borrowing_cost"], 2)},
                "Net Benefit": {"number": round(p["net_benefit"], 2)},
            })
        logger.info(f"Updated {len(analysis['ranked_payments'])} payments in queue")

    def _write_summary(self, analysis: dict):
        """Append payment optimization summary to CFO page."""
        blocks = [
            {"object": "block", "type": "divider", "divider": {}},
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": to_rich_text("Payment Optimization Report")}},
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": to_rich_text(
                 f"{analysis['payments_to_early_pay']}/{analysis['total_payments']} payments recommended for early pay | "
                 f"Total savings: ${analysis['total_discount_savings']:,.0f} | "
                 f"Borrowing cost: ${analysis['total_borrowing_cost']:,.0f}"
             )}},
        ]

        for p in analysis["ranked_payments"]:
            if p["recommendation"] == "Pay Early (Discount)":
                emoji = "💰"
            elif p["recommendation"] == "Pay on Due Date":
                emoji = "📅"
            elif p["recommendation"] == "Defer Payment":
                emoji = "⏳"
            else:
                emoji = "🤝"

            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": to_rich_text(
                        f"{emoji} #{p['priority_rank']} {p['vendor']} — "
                        f"${p['amount']:,.0f} — {p['recommendation']} "
                        f"(Net: ${p['net_benefit']:,.0f}, {p['days_to_due']}d to due)"
                    )
                }
            })

        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"},
                    "annotations": {"italic": True, "strikethrough": False,
                                    "underline": False, "code": False,
                                    "bold": False, "color": "gray"}
                }]
            }
        })

        self.client.append_blocks(config.PAGE_CFO_CENTER, blocks)
        logger.info("Payment optimization summary written to CFO page")
