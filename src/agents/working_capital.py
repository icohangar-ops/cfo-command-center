"""
CFO Command Center — Working Capital Optimizer Agent

Reads: Working Capital Tracker, AP/AR Aging, Vendor Scorecard
Writes: Updated AI Recommendation fields, new insights to CFO page
Actions: Analyzes CCC trends, identifies DSO/DPO/DIO optimization opportunities
"""

import logging
from datetime import datetime

from ..notion_client import (
    NotionClient, get_title, get_number, get_select,
    get_rich_text, to_rich_text
)
from .. import config

logger = logging.getLogger("agent.working_capital")


class WorkingCapitalAgent:
    """Analyzes working capital metrics and writes optimization recommendations."""

    def __init__(self, client: NotionClient):
        self.client = client
        self.db_id = config.DB_WORKING_CAPITAL
        self.aging_db = config.DB_AP_AR_AGING

    def run(self) -> dict:
        """Execute full analysis cycle. Returns summary dict."""
        logger.info("=== Working Capital Optimizer Agent START ===")
        periods = self._load_data()
        if not periods:
            logger.warning("No working capital data found.")
            return {"status": "no_data"}

        analysis = self._analyze(periods)
        self._write_recommendations(analysis)
        logger.info(f"Analysis complete: CCC={analysis['ccc']}d, trend={analysis['trend']}")
        logger.info("=== Working Capital Optimizer Agent END ===")
        return analysis

    # ── Data Loading ────────────────────────────────────────────────────

    def _load_data(self) -> list[dict]:
        results = self.client.query_database(
            self.db_id,
            sorts=[{"property": "Period", "direction": "ascending"}],
        )
        return results

    # ── Analysis ────────────────────────────────────────────────────────

    def _analyze(self, periods: list[dict]) -> dict:
        """Run working capital analysis across all periods."""
        latest = periods[-1]["properties"]
        previous = periods[-2]["properties"] if len(periods) >= 2 else None

        dso = get_number(latest, "DSO (Days Sales Outstanding)") or 0
        dpo = get_number(latest, "DPO (Days Payable Outstanding)") or 0
        dio = get_number(latest, "DIO (Days Inventory Outstanding)") or 0
        ccc = dso + dio - dpo
        nwc = get_number(latest, "Net Working Capital") or 0
        cash = get_number(latest, "Cash Position") or 0
        rev = get_number(latest, "Revenue (MTD)") or 0
        current_ratio = get_number(latest, "Current Ratio") or 0

        trend = get_select(latest, "CCC Trend") or "Unknown"

        # Calculate period-over-period changes
        changes = {}
        if previous:
            prev_dso = get_number(previous, "DSO (Days Sales Outstanding)") or 0
            prev_dpo = get_number(previous, "DPO (Days Payable Outstanding)") or 0
            prev_dio = get_number(previous, "DIO (Days Inventory Outstanding)") or 0
            prev_ccc = prev_dso + prev_dio - prev_dpo
            prev_nwc = get_number(previous, "Net Working Capital") or 0

            changes = {
                "dso_delta": dso - prev_dso,
                "dpo_delta": dpo - prev_dpo,
                "dio_delta": dio - prev_dio,
                "ccc_delta": ccc - prev_ccc,
                "nwc_delta": nwc - prev_nwc,
            }

        # Generate recommendations
        recommendations = self._generate_recommendations(
            dso, dpo, dio, ccc, nwc, cash, rev, current_ratio, changes
        )

        return {
            "period": get_title(latest, "Period"),
            "dso": dso, "dpo": dpo, "dio": dio, "ccc": ccc,
            "nwc": nwc, "cash": cash, "revenue": rev,
            "current_ratio": current_ratio,
            "trend": trend,
            "changes": changes,
            "recommendations": recommendations,
            "latest_page_id": periods[-1]["id"],
        }

    def _generate_recommendations(self, dso, dpo, dio, ccc, nwc, cash,
                                   rev, current_ratio, changes) -> list[str]:
        recs = []

        # CCC analysis
        if ccc > 40:
            recs.append(f"URGENT: CCC at {ccc}d is critically high. Immediate action needed on all three levers (DSO, DPO, DIO).")
        elif ccc > 30:
            recs.append(f"WARNING: CCC at {ccc}d is above the 30-day benchmark. Focus on DPO optimization.")
        elif ccc < 20:
            recs.append(f"STRONG: CCC at {ccc}d is excellent. Maintain current strategy and monitor for sustainability.")

        # DSO analysis
        if dso > 45:
            recs.append(f"DSO at {dso}d — collection cycle is too long. Consider tightening credit terms and activating collections on overdue AR.")
        elif changes.get("dso_delta", 0) < -2:
            recs.append(f"DSO improved by {abs(changes['dso_delta'])}d. Collections team performing well — consider incentive alignment.")

        # DPO analysis
        if dpo < 30:
            recs.append(f"DPO at {dpo}d — you are paying vendors faster than necessary. Negotiate Net 45-60 terms with Tier 1 vendors.")
        elif changes.get("dpo_delta", 0) > 2:
            recs.append(f"DPO extended by {changes['dpo_delta']}d. Payment term negotiations yielding results.")

        # DIO analysis
        if dio > 30:
            recs.append(f"DIO at {dio}d — excess inventory tying up cash. Review SKU-level demand forecasting and consider JIT for slow movers.")

        # Liquidity analysis
        if current_ratio < 1.5:
            recs.append(f"Current ratio at {current_ratio:.2f} — below the 1.5x safety threshold. Build cash reserves before discretionary CapEx.")
        elif current_ratio > 2.5:
            recs.append(f"Current ratio at {current_ratio:.2f} — excess liquidity. Consider investing surplus cash or accelerating strategic initiatives.")

        # NWC analysis
        if rev > 0:
            nwc_days = (nwc / rev) * 30 if rev else 0
            recs.append(f"NWC of ${nwc:,.0f} represents {nwc_days:.0f} days of revenue. Target: 60-90 days.")

        if not recs:
            recs.append("All working capital metrics within healthy range. Continue monitoring weekly.")

        return recs

    # ── Write Back ──────────────────────────────────────────────────────

    def _write_recommendations(self, analysis: dict):
        """Update the latest WC period with AI recommendations."""
        # Update the latest period row
        recommendation_text = "\n".join(
            f"• {r}" for r in analysis["recommendations"]
        )
        self.client.update_page(
            analysis["latest_page_id"],
            {"AI Recommendation": {"rich_text": to_rich_text(recommendation_text)}},
        )
        logger.info(f"Wrote {len(analysis['recommendations'])} recommendations to WC Tracker")

        # Also append insights to CFO Command Center page. Guard against
        # duplicate content when a webhook run and a batch run fire for the
        # same period concurrently — key on the period-tagged heading.
        insights = self._format_insights(analysis)
        self.client.append_blocks_idempotent(
            config.PAGE_CFO_CENTER, insights,
            dedup_key=f"wc-analysis:{analysis['period']}",
        )
        logger.info("Appended insights to CFO Command Center page")

    def _format_insights(self, analysis: dict) -> list[dict]:
        """Format analysis results as Notion blocks for the CFO page."""
        blocks = []
        blocks.append({
            "object": "block", "type": "divider", "divider": {}
        })
        blocks.append({
            "object": "block", "type": "heading_2",
            "heading_2": {
                "rich_text": to_rich_text(
                    f"WC Analysis — {analysis['period']}"
                )
            }
        })
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {
                "rich_text": to_rich_text(
                    f"CCC: {analysis['ccc']}d | DSO: {analysis['dso']}d | "
                    f"DPO: {analysis['dpo']}d | DIO: {analysis['dio']}d | "
                    f"Cash: ${analysis['cash']:,.0f} | Trend: {analysis['trend']}"
                )
            }
        })
        for rec in analysis["recommendations"]:
            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": to_rich_text(rec)}
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
        return blocks
