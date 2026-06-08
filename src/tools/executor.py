"""
CFO Command Center — NL Query Handler + Tool Executor

Processes natural language queries from Notion's built-in AI
(or any LLM) and routes them to the appropriate CFO Agent Tool.

This is the entry point for Notion AI integration — when a user
asks a question inside Notion, the AI calls these tools.

Usage:
    python -m src.tools.executor
"""

import json
import logging
import re
from typing import Optional

from ..notion_client import NotionClient, to_rich_text
from ..config import PAGE_CFO_CENTER
from .registry import ToolRegistry, TOOL_DEFINITIONS

logger = logging.getLogger("tool_executor")


# ── Intent Detection (keyword-based, no LLM dependency) ─────────────────

INTENT_PATTERNS = {
    "get_cash_position": [
        r"(what'?s|what is) (the |our )?cash (position|balance|on hand)",
        r"(how much|current) cash",
        r"(working capital|ccc|cash conversion)",
        r"financial (health|position|status)",
        r"(dso|dpo|dio|current ratio|quick ratio)",
        r"(how are|how is) (our |the )?(finances|liquidity)",
    ],
    "get_vendor_risk_summary": [
        r"(vendor|risk) (summary|report|status|overview)",
        r"(which|what) vendor(s)? (are|is) (at |high |critical )?risk",
        r"vendor (score|scorecard|performance)",
        r"(show|list|tell me about) (all |the )?vendor(s)?",
        r"(strategic|tier [123]) vendor(s)?",
    ],
    "get_cash_flow_forecast": [
        r"cash flow (forecast|projection|outlook|analysis)",
        r"(13.?week|weekly) (forecast|projection)",
        r"(future|upcoming|projected) cash",
        r"(will we run|running out of) cash",
        r"(cash shortfall|cash crunch|cash warning)",
        r"(burn rate|cash runway)",
    ],
    "evaluate_early_payment": [
        r"(should|can|do) (we |I )?(pay|make payment)",
        r"(early pay|discount|capture discount)",
        r"(pay .* early|early payment)",
        r"(evaluate|assess|analyze) (payment|invoice|discount)",
    ],
    "get_ap_ar_summary": [
        r"(ap|ar|accounts (payable|receivable))",
        r"(aging|aged) (report|summary|analysis)",
        r"(overdue|past due) (invoice|payment|items?)",
        r"(outstanding|unpaid|uncollected)",
        r"(disputed|dispute)",
    ],
    "get_payment_queue": [
        r"payment (queue|schedule|priority|optimization)",
        r"(what|which) payment(s)? (to |should|next)",
        r"(ranked|prioritized) (payment|invoice)",
        r"(discount savings|potential savings)",
    ],
    "get_working_capital_history": [
        r"(working capital) (history|trend|historical)",
        r"(ccc|dso|dpo|dio) (trend|history|over time|change)",
        r"(how has|how have) (working capital|ccc|cash) (changed|improved|evolved)",
        r"(monthly|period) (comparison|trend)",
    ],
}


class NLQueryHandler:
    """Routes natural language queries to the appropriate tool."""

    def __init__(self, client: NotionClient):
        self.client = client
        self.registry = ToolRegistry(client)

    def process_query(self, query: str) -> dict:
        """
        Process a natural language query and return the tool result.

        Args:
            query: Natural language question, e.g. "What's our cash position?"

        Returns:
            dict with 'tool', 'arguments', and 'result' keys.
        """
        query = query.strip().lower()
        logger.info(f"Processing NL query: '{query}'")

        # Detect intent
        tool_name = self._detect_intent(query)

        if not tool_name:
            return {
                "tool": None,
                "query": query,
                "result": {
                    "error": "Could not determine intent. Try rephrasing your question.",
                    "available_tools": list(TOOL_DEFINITIONS.keys()),
                    "examples": [
                        "What's our cash position?",
                        "Which vendors are at risk?",
                        "Show me the cash flow forecast",
                        "Should we pay Acme Steel early?",
                        "What's the AP/AR aging summary?",
                        "Show the payment queue",
                    ],
                },
            }

        # Extract arguments
        arguments = self._extract_arguments(tool_name, query)

        # Invoke tool
        result = self.registry.invoke(tool_name, arguments)

        return {
            "tool": tool_name,
            "arguments": arguments,
            "result": result,
        }

    def detect_intent(self, query: str) -> Optional[str]:
        """Detect which tool to invoke based on the query text."""
        return self._detect_intent(query.lower())

    def _detect_intent(self, query: str) -> Optional[str]:
        for tool_name, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    return tool_name
        return None

    def _extract_arguments(self, tool_name: str, query: str) -> dict:
        """Extract structured arguments from a natural language query."""
        args = {}

        if tool_name == "get_vendor_risk_summary":
            for level in ["Low", "Medium", "High", "Critical"]:
                if level.lower() in query:
                    args["risk_level"] = level
                    break

        elif tool_name == "get_cash_flow_forecast":
            weeks_match = re.search(r"(\d+)\s*week", query)
            if weeks_match:
                args["weeks"] = int(weeks_match.group(1))

        elif tool_name == "evaluate_early_payment":
            # Try to extract vendor name, amount, and terms
            # Pattern: "should we pay [vendor] [amount] early"
            amount_match = re.search(r"\$?([\d,]+(?:\.\d{2})?)", query)
            if amount_match:
                args["invoice_amount"] = float(amount_match.group(1).replace(",", ""))

            # Look for discount terms
            terms_match = re.search(r"(\d+)/(\d+)\s*(net|Net)\s*(\d+)", query)
            if terms_match:
                args["discount_terms"] = f"{terms_match.group(1)}/{terms_match.group(2)} Net {terms_match.group(4)}"

            # Look for days
            days_match = re.search(r"(\d+)\s*days?\s*(to|until|before)", query)
            if days_match:
                args["days_to_due_date"] = int(days_match.group(1))

        elif tool_name == "get_ap_ar_summary":
            if "ap" in query and "ar" not in query:
                args["type"] = "AP"
            elif "ar" in query and "ap" not in query:
                args["type"] = "AR"

        elif tool_name == "get_payment_queue":
            for status in ["Queued", "Approved", "Processing", "Completed"]:
                if status.lower() in query:
                    args["status"] = status
                    break

        return args

    def format_result_as_text(self, response: dict) -> str:
        """Format a tool response as human-readable text for Notion display."""
        tool = response.get("tool")
        result = response.get("result", {})

        if "error" in result and tool is None:
            return f"Could not understand your query. Available tools: {', '.join(result.get('available_tools', []))}"

        if "error" in result:
            return f"Error: {result['error']}"

        formatters = {
            "get_cash_position": self._format_cash_position,
            "get_vendor_risk_summary": self._format_vendor_summary,
            "get_cash_flow_forecast": self._format_cash_flow,
            "evaluate_early_payment": self._format_payment_eval,
            "get_ap_ar_summary": self._format_ap_ar,
            "get_payment_queue": self._format_payment_queue,
            "get_working_capital_history": self._format_wc_history,
            "create_vendor_alert": self._format_alert_created,
        }

        formatter = formatters.get(tool)
        if formatter:
            return formatter(result)
        return json.dumps(result, indent=2, default=str)

    def _format_cash_position(self, r: dict) -> str:
        return (
            f"Cash Position Report — {r['period']}\n"
            f"{'─' * 40}\n"
            f"Cash on Hand:      ${r['cash_position']:>12,.0f}\n"
            f"Net Working Cap:   ${r['net_working_capital']:>12,.0f}\n"
            f"{'─' * 40}\n"
            f"CCC:               {r['ccc']:>8} days\n"
            f"DSO:               {r['dso']:>8} days\n"
            f"DPO:               {r['dpo']:>8} days\n"
            f"DIO:               {r['dio']:>8} days\n"
            f"{'─' * 40}\n"
            f"Current Ratio:     {r['current_ratio']:>8.2f}x\n"
            f"Quick Ratio:       {r['quick_ratio']:>8.2f}x\n"
            f"{'─' * 40}\n"
            f"Revenue (MTD):     ${r['revenue_mtd']:>12,.0f}\n"
            f"AR Balance:        ${r['ar_balance']:>12,.0f}\n"
            f"AP Balance:        ${r['ap_balance']:>12,.0f}\n"
            f"Short-Term Debt:   ${r['short_term_debt']:>12,.0f}\n"
            f"Trend:             {r['trend']}\n"
        )

    def _format_vendor_summary(self, r: dict) -> str:
        lines = [
            f"Vendor Risk Summary — {r['total_vendors']} vendors, ${r['total_annual_spend']:,.0f} total spend",
            f"Risk Breakdown: {', '.join(f'{k}: {v}' for k, v in r['risk_breakdown'].items())}",
            "",
        ]
        for v in r["vendors"]:
            lines.append(
                f"  {'⚠️' if v['risk_rating'] in ('High', 'Critical') else '✅'} "
                f"{v['name']:<25s} | ${v['annual_spend']:>9,.0f} | "
                f"Risk: {v['risk_rating']:<8s} | OTD: {v['on_time_delivery']:.0%} | "
                f"Tier: {v['strategic_priority']}"
            )
        return "\n".join(lines)

    def _format_cash_flow(self, r: dict) -> str:
        lines = [
            f"13-Week Cash Flow Forecast",
            f"Total Inflows: ${r['total_inflows']:,.0f} | Outflows: ${r['total_outflows']:,.0f} | Net: ${r['net_position']:,.0f}",
            f"Min Closing Balance: ${r['min_closing_balance']:,.0f} ({r['min_closing_week']})",
            "",
        ]
        for w in r["forecast"]:
            status_emoji = {"Actual": "●", "Forecast": "○", "Revised": "◐"}.get(w["status"], "·")
            lines.append(
                f"  {status_emoji} {w['week']:<16s} | In: ${w['cash_inflows']:>9,.0f} | "
                f"Out: ${w['cash_outflows']:>9,.0f} | Net: ${w['net_cash_flow']:>+9,.0f} | "
                f"Close: ${w['closing_balance']:>10,.0f}"
            )
        return "\n".join(lines)

    def _format_payment_eval(self, r: dict) -> str:
        return (
            f"Early Payment Evaluation: {r['vendor']}\n"
            f"{'─' * 40}\n"
            f"Invoice Amount:       ${r['invoice_amount']:>12,.0f}\n"
            f"Discount Terms:       {r['discount_terms']}\n"
            f"Days to Due Date:     {r['days_to_due_date']:>8}\n"
            f"{'─' * 40}\n"
            f"Discount Savings:     ${r['discount_savings']:>12,.2f}\n"
            f"Borrowing Cost:       ${r['borrowing_cost']:>12,.2f}\n"
            f"Net Benefit:          ${r['net_benefit']:>12,.2f}\n"
            f"Annualized Rate:      {r['annualized_rate_pct']:>8.2f}%\n"
            f"{'─' * 40}\n"
            f"RECOMMENDATION: {r['recommendation']}\n"
        )

    def _format_ap_ar(self, r: dict) -> str:
        lines = [
            f"AP/AR Aging Summary — Total Outstanding: ${r['total_outstanding']:,.0f}",
            "",
            "  Aging Buckets:",
        ]
        for bucket, amount in r["aging_buckets"].items():
            pct = (amount / r["total_outstanding"] * 100) if r["total_outstanding"] else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            lines.append(f"    {bucket:<12s} ${amount:>10,.0f}  {bar} {pct:.0f}%")

        lines.append("")
        for t, data in r["by_type"].items():
            lines.append(f"  {t}: {data['count']} items, ${data['total']:,.0f}")
        lines.append(f"  Overdue: {r['overdue_count']} items (${r['overdue_total']:,.0f})")
        lines.append(f"  Disputed: {r['disputed_count']} items (${r['disputed_total']:,.0f})")
        return "\n".join(lines)

    def _format_payment_queue(self, r: dict) -> str:
        lines = [
            f"Payment Optimization Queue — {r['total_payments']} payments, ${r['total_potential_savings']:,.0f} savings",
            "",
        ]
        for p in r["payments"]:
            rec_emoji = {"Pay Early (Discount)": "💰", "Pay on Due Date": "📅",
                         "Defer Payment": "⏳", "Negotiate Terms": "🤝"}.get(p["recommendation"], "·")
            lines.append(
                f"  #{p['rank']} {rec_emoji} {p['vendor']:<30s} | ${p['amount']:>9,.0f} | "
                f"Net: ${p['net_benefit']:>8,.0f} | {p['recommendation']}"
            )
        return "\n".join(lines)

    def _format_wc_history(self, r: dict) -> str:
        lines = ["Working Capital History", ""]
        for p in r["periods"]:
            trend_emoji = {"Improving": "📈", "Stable": "➡️", "Worsening": "📉"}.get(p["trend"], "·")
            lines.append(
                f"  {trend_emoji} {p['period']:<12s} | CCC: {p['ccc']:>3d}d | "
                f"DSO: {p['dso']:>2d} DPO: {p['dpo']:>2d} DIO: {p['dio']:>2d} | "
                f"Cash: ${p['cash_position']:>9,.0f} | CR: {p['current_ratio']:.2f}"
            )
        if r.get("trends"):
            t = r["trends"]
            direction = "improved" if t["ccc_change"] < 0 else "worsened"
            lines.append(f"\n  CCC {direction} by {abs(t['ccc_change'])}d | Cash {'grew' if t['cash_change'] >= 0 else 'declined'} by ${abs(t['cash_change']):,.0f}")
        return "\n".join(lines)

    def _format_alert_created(self, r: dict) -> str:
        return f"Alert created successfully.\nEntity: {r['entity']}\nMessage: {r['message']}"


class ToolExecutor:
    """
    Full tool execution pipeline.

    Handles:
    1. Direct tool invocation (programmatic)
    2. NL query processing (from Notion AI / chat)
    3. Writing results back to Notion pages
    """

    def __init__(self, client: NotionClient):
        self.client = client
        self.registry = ToolRegistry(client)
        self.nl_handler = NLQueryHandler(client)

    def invoke_tool(self, tool_name: str, arguments: dict = None) -> dict:
        """Invoke a specific tool by name with arguments."""
        return self.registry.invoke(tool_name, arguments)

    def ask(self, question: str, write_to_notion: bool = False) -> dict:
        """
        Process a natural language question and optionally write
        the result to the CFO Command Center page.

        Args:
            question: Natural language question
            write_to_notion: If True, writes formatted result to Notion

        Returns:
            dict with tool, arguments, result, and formatted_text
        """
        response = self.nl_handler.process_query(question)
        formatted = self.nl_handler.format_result_as_text(response)

        if write_to_notion and response.get("tool"):
            self._write_to_notion(question, response, formatted)

        return {
            **response,
            "formatted_text": formatted,
        }

    def list_tools(self) -> list[dict]:
        """Return all available tool definitions."""
        return self.registry.list_tools()

    def _write_to_notion(self, question: str, response: dict, formatted_text: str):
        """Write a Q&A result to the CFO Command Center page."""
        from datetime import datetime, timezone

        blocks = [
            {"object": "block", "type": "divider", "divider": {}},
            {"object": "block", "type": "heading_3",
             "heading_3": {"rich_text": to_rich_text(f"CFO AI Query: {question[:80]}")}},
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": to_rich_text(f"Tool: {response.get('tool', 'N/A')}")}},
            {"object": "block", "type": "code",
             "code": {
                 "rich_text": to_rich_text(formatted_text),
                 "language": "plain text",
             }},
            {"object": "block", "type": "paragraph",
             "paragraph": {
                 "rich_text": [{
                     "type": "text",
                     "text": {"content": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")},
                     "annotations": {"italic": True, "strikethrough": False,
                                     "underline": False, "code": False,
                                     "bold": False, "color": "gray"}
                 }]
             }},
        ]
        self.client.append_blocks(PAGE_CFO_CENTER, blocks)
        logger.info(f"Wrote Q&A result to Notion for: {question[:50]}")


# ── CLI Interface ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    from ..config import NOTION_TOKEN

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    client = NotionClient(token=NOTION_TOKEN)
    executor = ToolExecutor(client)

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        print("CFO Command Center — AI Tool Executor")
        print("Available tools:")
        for t in TOOL_DEFINITIONS.values():
            print(f"  • {t['name']}: {t['description'][:70]}...")
        print("\nExample queries:")
        print('  python -m src.tools.executor "What is our cash position?"')
        print('  python -m src.tools.executor "Which vendors are at risk?"')
        print('  python -m src.tools.executor "Show the payment queue"')
        print('  python -m src.tools.executor "Evaluate early payment for Acme Steel $198000 2/10 Net 30 30 days"')
        print()
        query = input("Ask a question: ")

    result = executor.ask(query, write_to_notion=True)
    print(result["formatted_text"])
