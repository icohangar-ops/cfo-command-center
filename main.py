"""
CFO Command Center — Main Orchestration Layer

Runs all finance agents in sequence and writes a consolidated
executive summary to the CFO Command Center page.
"""

import logging
import time
from datetime import datetime

from src.config import NOTION_TOKEN, PAGE_CFO_CENTER
from src.notion_client import NotionClient, to_rich_text
from src.agents.working_capital import WorkingCapitalAgent
from src.agents.cash_flow import CashFlowAgent
from src.agents.payment_optimization import PaymentOptimizationAgent
from src.agents.vendor_risk import VendorRiskAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("cfo_command_center")


def run_all_agents() -> dict:
    """Execute all finance agents and return consolidated results."""
    logger.info("=" * 60)
    logger.info("  CFO COMMAND CENTER — FULL AGENT CYCLE")
    logger.info(f"  Started at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    logger.info("=" * 60)

    client = NotionClient(token=NOTION_TOKEN)
    results = {}

    # ── Agent 1: Working Capital Optimizer ─────────────────────────────
    t0 = time.time()
    try:
        wc_agent = WorkingCapitalAgent(client)
        results["working_capital"] = wc_agent.run()
    except Exception as e:
        logger.error(f"Working Capital Agent failed: {e}")
        results["working_capital"] = {"status": "error", "message": str(e)}
    results["working_capital"]["duration"] = round(time.time() - t0, 2)

    # ── Agent 2: Cash Flow Forecast ────────────────────────────────────
    t0 = time.time()
    try:
        cf_agent = CashFlowAgent(client)
        results["cash_flow"] = cf_agent.run()
    except Exception as e:
        logger.error(f"Cash Flow Agent failed: {e}")
        results["cash_flow"] = {"status": "error", "message": str(e)}
    results["cash_flow"]["duration"] = round(time.time() - t0, 2)

    # ── Agent 3: Payment Optimization ──────────────────────────────────
    t0 = time.time()
    try:
        po_agent = PaymentOptimizationAgent(client)
        results["payment_optimization"] = po_agent.run()
    except Exception as e:
        logger.error(f"Payment Optimization Agent failed: {e}")
        results["payment_optimization"] = {"status": "error", "message": str(e)}
    results["payment_optimization"]["duration"] = round(time.time() - t0, 2)

    # ── Agent 4: Vendor Risk Analyzer ──────────────────────────────────
    t0 = time.time()
    try:
        vr_agent = VendorRiskAgent(client)
        results["vendor_risk"] = vr_agent.run()
    except Exception as e:
        logger.error(f"Vendor Risk Agent failed: {e}")
        results["vendor_risk"] = {"status": "error", "message": str(e)}
    results["vendor_risk"]["duration"] = round(time.time() - t0, 2)

    # ── Executive Summary ──────────────────────────────────────────────
    _write_executive_summary(client, results)

    logger.info("=" * 60)
    logger.info("  CFO COMMAND CENTER — CYCLE COMPLETE")
    logger.info("=" * 60)
    return results


def _write_executive_summary(client: NotionClient, results: dict):
    """Write a consolidated executive summary to the CFO page."""
    blocks = [
        {"object": "block", "type": "divider", "divider": {}},
        {"object": "block", "type": "heading_1",
         "heading_1": {"rich_text": to_rich_text("Executive Summary")}},
        {"object": "block", "type": "callout",
         "callout": {
             "icon": {"emoji": "🤖"},
             "rich_text": to_rich_text(
                 f"AI Agent Analysis — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
             )
         }},
    ]

    # Working Capital summary
    wc = results.get("working_capital", {})
    if wc.get("status") != "error" and wc.get("status") != "no_data":
        blocks.append({
            "object": "block", "type": "heading_3",
            "heading_3": {"rich_text": to_rich_text("Working Capital")}},
        )
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": to_rich_text(
                f"CCC: {wc.get('ccc', 'N/A')}d | Cash: ${wc.get('cash', 0):,.0f} | "
                f"trend: {wc.get('trend', 'N/A')} | {len(wc.get('recommendations', []))} recommendations"
            )}},
        )

    # Cash Flow summary
    cf = results.get("cash_flow", {})
    if cf.get("status") != "error" and cf.get("status") != "no_data":
        blocks.append({
            "object": "block", "type": "heading_3",
            "heading_3": {"rich_text": to_rich_text("Cash Flow Forecast")}},
        )
        critical = sum(1 for a in cf.get("alerts", []) if a["severity"] == "CRITICAL")
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": to_rich_text(
                f"13-week net: ${cf.get('net_position', 0):,.0f} | "
                f"Min closing: ${cf.get('min_closing_balance', 0):,.0f} | "
                f"Critical alerts: {critical}"
            )}},
        )

    # Payment Optimization summary
    po = results.get("payment_optimization", {})
    if po.get("status") != "error" and po.get("status") != "no_data":
        blocks.append({
            "object": "block", "type": "heading_3",
            "heading_3": {"rich_text": to_rich_text("Payment Optimization")}},
        )
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": to_rich_text(
                f"Savings identified: ${po.get('total_discount_savings', 0):,.0f} | "
                f"Early pay recommended: {po.get('payments_to_early_pay', 0)}/{po.get('total_payments', 0)} payments"
            )}},
        )

    # Vendor Risk summary
    vr = results.get("vendor_risk", {})
    if vr.get("status") != "error" and vr.get("status") != "no_data":
        blocks.append({
            "object": "block", "type": "heading_3",
            "heading_3": {"rich_text": to_rich_text("Vendor Risk")}},
        )
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": to_rich_text(
                f"At-risk vendors: {vr.get('at_risk_count', 0)} | "
                f"Spend at risk: ${vr.get('total_spend_at_risk', 0):,.0f} | "
                f"Contract warnings: {vr.get('contract_warnings_count', 0)}"
            )}},
        )

    # Agent performance
    total_time = sum(r.get("duration", 0) for r in results.values())
    blocks.append({
        "object": "block", "type": "divider", "divider": {}
    })
    blocks.append({
        "object": "block", "type": "paragraph",
        "paragraph": {
            "rich_text": [{
                "type": "text",
                "text": {"content": f"Agent cycle completed in {total_time:.1f}s"},
                "annotations": {"italic": True, "strikethrough": False,
                                "underline": False, "code": False,
                                "bold": False, "color": "gray"}
            }]
        }
    })

    client.append_blocks(PAGE_CFO_CENTER, blocks)
    logger.info("Executive summary written to CFO page")


if __name__ == "__main__":
    run_all_agents()
