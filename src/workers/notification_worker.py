"""
CFO Command Center — Notification Worker

Sends alerts and notifications based on finance agent results.
Supports Slack webhook integration and console/email fallback.

Usage:
    python -m src.workers.notification_worker

Set environment variable SLACK_WEBHOOK_URL to enable Slack notifications.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from ..config import NOTION_TOKEN, PAGE_CFO_CENTER
from ..notion_client import NotionClient, to_rich_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("notification_worker")


class NotificationWorker:
    """
    Sends alerts based on finance analysis results.

    Alert triggers:
    - Cash position below threshold ($100K, $500K)
    - CCC exceeding benchmark (>40 days)
    - Vendor risk upgrade
    - Payment discount deadline approaching
    - Overdue invoice escalation
    """

    def __init__(self, client: NotionClient, slack_webhook_url: Optional[str] = None):
        self.client = client
        self.slack_url = slack_webhook_url
        self.alert_log: list[dict] = []

    def check_and_alert(self, analysis_results: dict) -> dict:
        """
        Run all alert checks against analysis results.
        Returns summary of alerts sent.
        """
        alerts_sent = {"slack": 0, "notion": 0, "console": 0}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Check each result set
        wc = analysis_results.get("working_capital", {})
        cf = analysis_results.get("cash_flow", {})
        po = analysis_results.get("payment_optimization", {})
        vr = analysis_results.get("vendor_risk", {})

        # ── Cash Position Alerts ─────────────────────────────────────
        if wc.get("status") == "success":
            cash = wc.get("cash", 0)
            if cash < 100000:
                self._send_alert(
                    severity="CRITICAL",
                    title="Cash Position Critical",
                    message=f"Cash on hand dropped to ${cash:,.0f}. Immediate action required.",
                    channel="all",
                )
            elif cash < 500000:
                self._send_alert(
                    severity="WARNING",
                    title="Cash Position Low",
                    message=f"Cash on hand at ${cash:,.0f}. Below $500K safety threshold.",
                    channel="all",
                )

        # ── CCC Alerts ───────────────────────────────────────────────
        if wc.get("status") == "success":
            ccc = wc.get("ccc", 0)
            if ccc > 45:
                self._send_alert(
                    severity="CRITICAL",
                    title="CCC Critically High",
                    message=f"Cash Conversion Cycle at {ccc} days. Working capital efficiency severely degraded.",
                    channel="all",
                )
            elif ccc > 35:
                self._send_alert(
                    severity="WARNING",
                    title="CCC Above Benchmark",
                    message=f"CCC at {ccc} days, above the 35-day warning threshold.",
                    channel="notion",
                )

        # ── Cash Flow Shortfall Alerts ───────────────────────────────
        if cf.get("status") == "success":
            for alert in cf.get("alerts", []):
                if alert["severity"] in ("CRITICAL", "WARNING"):
                    self._send_alert(
                        severity=alert["severity"],
                        title=f"Cash Flow Alert: {alert['week']}",
                        message=alert["message"],
                        channel="all" if alert["severity"] == "CRITICAL" else "notion",
                    )

        # ── Vendor Risk Alerts ───────────────────────────────────────
        if vr.get("status") == "success":
            for v in vr.get("at_risk", []):
                if v.get("risk_changed"):
                    self._send_alert(
                        severity="WARNING" if v["new_risk"] == "High" else "CRITICAL",
                        title=f"Vendor Risk Upgrade: {v['vendor']}",
                        message=f"Risk upgraded from {v['current_risk']} to {v['new_risk']}. "
                                f"OTD: {v['otd']:.0%}, Quality: {v['quality']}, "
                                f"Annual Spend: ${v['spend']:,.0f}.",
                        channel="all" if v["new_risk"] == "Critical" else "notion",
                    )

            for w in vr.get("contract_warnings", []):
                self._send_alert(
                    severity="WARNING",
                    title=f"Contract Expiring: {w['vendor']}",
                    message=f"Contract expires in {w['days_left']} days. "
                            f"Tier: {w['tier']}, Annual Spend: ${w['spend']:,.0f}.",
                    channel="notion",
                )

        # ── Payment Discount Deadline Alerts ─────────────────────────
        if po.get("status") == "success":
            for p in po.get("ranked_payments", []):
                if p.get("recommendation") == "Pay Early (Discount)" and p.get("days_to_due", 99) <= 5:
                    self._send_alert(
                        severity="WARNING",
                        title=f"Discount Expiring: {p.get('vendor', 'Unknown')}",
                        message=f"${p.get('amount', 0):,.0f} payment has early-pay discount expiring in "
                                f"{p.get('days_to_due', 0)} days. Net benefit: ${p.get('net_benefit', 0):,.0f}.",
                        channel="all",
                    )

        # Write alert log to Notion
        if self.alert_log:
            self._write_alert_log()
            logger.info(f"Total alerts processed: {len(self.alert_log)}")

        return {
            "timestamp": now,
            "total_alerts": len(self.alert_log),
            "alerts_sent": alerts_sent,
        }

    def _send_alert(self, severity: str, title: str, message: str,
                    channel: str = "all"):
        """Route an alert to the specified channels."""
        alert = {
            "severity": severity,
            "title": title,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.alert_log.append(alert)

        emoji = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(severity, "⚪")

        # Console (always)
        logger.warning(f"{emoji} [{severity}] {title}: {message[:100]}")

        # Notion
        if channel in ("all", "notion"):
            self._write_alert_to_notion(alert, emoji)

        # Slack
        if channel in ("all", "slack") and self.slack_url:
            self._send_slack_alert(alert, emoji)

    def _write_alert_to_notion(self, alert: dict, emoji: str):
        """Append a single alert to the CFO Command Center page."""
        blocks = [
            {"object": "block", "type": "callout",
             "callout": {
                 "icon": {"emoji": emoji},
                 "rich_text": to_rich_text(
                     f"[{alert['severity']}] {alert['title']}\n{alert['message']}"
                 ),
             }},
        ]
        try:
            self.client.append_blocks(PAGE_CFO_CENTER, blocks)
        except Exception as e:
            logger.error(f"Failed to write alert to Notion: {e}")

    def _write_alert_log(self):
        """Write the full alert log as a summary section to Notion."""
        critical = sum(1 for a in self.alert_log if a["severity"] == "CRITICAL")
        warnings = sum(1 for a in self.alert_log if a["severity"] == "WARNING")
        info = sum(1 for a in self.alert_log if a["severity"] == "INFO")

        blocks = [
            {"object": "block", "type": "divider", "divider": {}},
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": to_rich_text(
                 f"Alert Log — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
             )}},
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": to_rich_text(
                 f"Critical: {critical} | Warnings: {warnings} | Info: {info}"
             )}},
        ]
        self.client.append_blocks(PAGE_CFO_CENTER, blocks)

    def _send_slack_alert(self, alert: dict, emoji: str):
        """Send an alert to Slack via webhook."""
        try:
            color = {"CRITICAL": "#FF0000", "WARNING": "#FFA500", "INFO": "#4169E1"}.get(alert["severity"], "#808080")
            payload = json.dumps({
                "attachments": [{
                    "color": color,
                    "title": f"{emoji} CFO Alert: {alert['title']}",
                    "text": alert["message"],
                    "footer": "CFO Command Center",
                    "ts": int(datetime.now(timezone.utc).timestamp()),
                }]
            }).encode()

            req = Request(self.slack_url, data=payload,
                          headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=10) as resp:
                logger.debug(f"Slack alert sent: {alert['title']}")
        except (URLError, Exception) as e:
            logger.error(f"Slack alert failed: {e}")


if __name__ == "__main__":
    from ..notion_client import NotionClient
    import os

    client = NotionClient(token=NOTION_TOKEN)
    slack_url = os.getenv("SLACK_WEBHOOK_URL")

    worker = NotificationWorker(client, slack_webhook_url=slack_url)

    # Run a quick check by loading current data
    from ..agents.working_capital import WorkingCapitalAgent
    from ..agents.cash_flow import CashFlowAgent
    from ..agents.vendor_risk import VendorRiskAgent

    results = {}
    try:
        results["working_capital"] = WorkingCapitalAgent(client).run()
    except Exception:
        results["working_capital"] = {"status": "error"}
    try:
        results["cash_flow"] = CashFlowAgent(client).run()
    except Exception:
        results["cash_flow"] = {"status": "error"}
    try:
        results["vendor_risk"] = VendorRiskAgent(client).run()
    except Exception:
        results["vendor_risk"] = {"status": "error"}

    summary = worker.check_and_alert(results)
    print(json.dumps(summary, indent=2))
