"""
CFO Command Center — Cash Flow Forecast Agent

Reads: Cash Flow Forecast database
Writes: Updated confidence levels, variance flags, AI-generated revisions
Actions: Detects cash shortfalls, recommends borrowing/surplus deployment
"""

import logging
from datetime import datetime

from ..notion_client import (
    NotionClient, get_title, get_number, get_select,
    get_rich_text, to_rich_text, get_formula_number
)
from .. import config

logger = logging.getLogger("agent.cash_flow")


class CashFlowAgent:
    """Analyzes 13-week cash flow forecast and writes AI-driven adjustments."""

    def __init__(self, client: NotionClient):
        self.client = client
        self.db_id = config.DB_CASH_FLOW_FORECAST

    def run(self) -> dict:
        logger.info("=== Cash Flow Forecast Agent START ===")
        weeks = self._load_data()
        if not weeks:
            logger.warning("No cash flow data found.")
            return {"status": "no_data"}

        analysis = self._analyze(weeks)
        self._write_analysis(analysis)
        logger.info(
            f"Analysis complete: {len(analysis['alerts'])} alerts, "
            f"min closing balance ${analysis['min_closing_balance']:,.0f}"
        )
        logger.info("=== Cash Flow Forecast Agent END ===")
        return analysis

    # ── Data Loading ────────────────────────────────────────────────────

    def _load_data(self) -> list[dict]:
        return self.client.query_database(
            self.db_id,
            sorts=[{"property": "Week", "direction": "ascending"}],
        )

    # ── Analysis ────────────────────────────────────────────────────────

    def _analyze(self, weeks: list[dict]) -> dict:
        alerts = []
        min_closing = float("inf")
        min_week = ""
        surplus_weeks = []
        total_inflows = 0
        total_outflows = 0

        for w in weeks:
            props = w["properties"]
            week = get_title(props, "Week")
            opening = get_number(props, "Opening Balance") or 0
            inflows = get_number(props, "Cash Inflows") or 0
            outflows = get_number(props, "Cash Outflows") or 0
            net = inflows - outflows
            closing = opening + net
            status = get_select(props, "Week Status") or "Forecast"
            confidence = get_select(props, "Confidence Level") or "Medium"

            total_inflows += inflows
            total_outflows += outflows

            if closing < min_closing:
                min_closing = closing
                min_week = week

            # Cash shortfall detection
            if closing < 100000 and status == "Forecast":
                alerts.append({
                    "severity": "CRITICAL",
                    "week": week,
                    "message": f"Closing balance drops to ${closing:,.0f} in {week}. Immediate cash management action required. Consider drawing on credit facility or accelerating AR collections.",
                    "page_id": w["id"],
                })
            elif closing < 500000 and status == "Forecast":
                alerts.append({
                    "severity": "WARNING",
                    "week": week,
                    "message": f"Closing balance at ${closing:,.0f} in {week}. Below $500K safety threshold. Review AP timing and defer discretionary spend.",
                    "page_id": w["id"],
                })

            # Surplus detection
            if closing > 3000000 and status == "Forecast":
                surplus_weeks.append({
                    "week": week,
                    "surplus": closing - 2000000,
                })

            # Variance analysis for actual weeks
            if status == "Actual":
                variance = get_number(props, "Variance vs Forecast") or 0
                var_pct = get_number(props, "Variance Pct") or 0
                if abs(var_pct) > 0.10:
                    direction = "overperformed" if var_pct > 0 else "underperformed"
                    alerts.append({
                        "severity": "INFO",
                        "week": week,
                        "message": f"Actual vs Forecast variance: {var_pct*100:+.1f}% ({direction}) in {week}. ${variance:+,.0f} difference.",
                        "page_id": w["id"],
                    })

        # Generate recommendations
        recommendations = self._generate_recommendations(
            alerts, min_closing, min_week, surplus_weeks, total_inflows, total_outflows
        )

        return {
            "total_weeks": len(weeks),
            "total_inflows": total_inflows,
            "total_outflows": total_outflows,
            "net_position": total_inflows - total_outflows,
            "min_closing_balance": min_closing,
            "min_closing_week": min_week,
            "alerts": alerts,
            "surplus_weeks": surplus_weeks,
            "recommendations": recommendations,
        }

    def _generate_recommendations(self, alerts, min_closing, min_week,
                                   surplus_weeks, total_in, total_out) -> list[str]:
        recs = []

        critical = [a for a in alerts if a["severity"] == "CRITICAL"]
        warnings = [a for a in alerts if a["severity"] == "WARNING"]

        if critical:
            recs.append(f"CASH CRISIS: {len(critical)} week(s) project closing below $100K. Activate contingency: (1) Accelerate AR collections on top 5 clients, (2) Defer non-critical AP, (3) Draw on revolving credit facility.")

        if min_closing < 500000:
            recs.append(f"LOW RESERVE: Minimum projected closing balance ${min_closing:,.0f} in {min_week}. Build 60-day cash buffer target of $600K.")

        if surplus_weeks:
            total_surplus = sum(s["surplus"] for s in surplus_weeks)
            recs.append(f"SURPLUS DETECTED: {len(surplus_weeks)} week(s) with excess cash totaling ${total_surplus:,.0f}. Consider short-term money market placement or early debt repayment.")

        # Cash burn rate
        avg_weekly_net = (total_in - total_out) / 13 if total_in else 0
        if avg_weekly_net < 0:
            weeks_runway = min_closing / abs(avg_weekly_net) if avg_weekly_net != 0 else 0
            recs.append(f"BURN RATE: Average weekly net cash flow is ${avg_weekly_net:,.0f}. At current burn, cash reserves last ~{weeks_runway:.0f} weeks. Revenue acceleration or cost reduction needed.")

        recs.append(f"13-WEEK SUMMARY: Total inflows ${total_in:,.0f}, outflows ${total_out:,.0f}, net ${total_in - total_out:,.0f}.")

        return recs

    # ── Write Back ──────────────────────────────────────────────────────

    def _write_analysis(self, analysis: dict):
        """Append cash flow analysis to CFO Command Center page."""
        blocks = []
        blocks.append({
            "object": "block", "type": "divider", "divider": {}
        })
        blocks.append({
            "object": "block", "type": "heading_2",
            "heading_2": {"rich_text": to_rich_text("Cash Flow Forecast Analysis")}
        })
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {
                "rich_text": to_rich_text(
                    f"13-Week Net: ${analysis['net_position']:,.0f} | "
                    f"Min Closing: ${analysis['min_closing_balance']:,.0f} ({analysis['min_closing_week']}) | "
                    f"Alerts: {len(analysis['alerts'])}"
                )
            }
        })

        for alert in analysis["alerts"]:
            severity_emoji = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(alert["severity"], "⚪")
            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": to_rich_text(f"{severity_emoji} [{alert['severity']}] {alert['message']}")
                }
            })

        for rec in analysis["recommendations"]:
            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": to_rich_text(f"→ {rec}")}
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
        logger.info(f"Wrote cash flow analysis to CFO page ({len(analysis['alerts'])} alerts)")
