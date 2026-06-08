"""
CFO Command Center — Vendor Risk Analyzer Agent

Reads: Vendor Scorecard, AP/AR Aging
Writes: Updated risk ratings, vendor health alerts to CFO page
Actions: Flags at-risk vendors, contract renewal warnings, payment priority adjustments
"""

import logging
from datetime import datetime

from ..notion_client import (
    NotionClient, get_title, get_number, get_select, get_date,
    to_rich_text
)
from .. import config

logger = logging.getLogger("agent.vendor_risk")


class VendorRiskAgent:
    """Analyzes vendor health and risk, updates scorecards with AI assessments."""

    def __init__(self, client: NotionClient):
        self.client = client
        self.vendor_db = config.DB_VENDOR_SCORECARD
        self.aging_db = config.DB_AP_AR_AGING

    def run(self) -> dict:
        logger.info("=== Vendor Risk Analyzer Agent START ===")
        vendors = self._load_vendors()
        aging = self._load_aging()

        if not vendors:
            logger.warning("No vendor data found.")
            return {"status": "no_data"}

        analysis = self._analyze(vendors, aging)
        self._update_risk_ratings(analysis)
        self._write_alerts(analysis)
        logger.info(
            f"Analysis complete: {analysis['at_risk_count']} at-risk vendors, "
            f"{analysis['contract_warnings']} contract renewal warnings"
        )
        logger.info("=== Vendor Risk Analyzer Agent END ===")
        return analysis

    # ── Data Loading ────────────────────────────────────────────────────

    def _load_vendors(self) -> list[dict]:
        return self.client.query_database(self.vendor_db)

    def _load_aging(self) -> list[dict]:
        return self.client.query_database(self.aging_db)

    # ── Analysis ────────────────────────────────────────────────────────

    def _analyze(self, vendors: list[dict], aging: list[dict]) -> dict:
        at_risk = []
        contract_warnings = []
        high_performers = []
        total_spend_at_risk = 0

        today = datetime.utcnow()

        # Build aging map by vendor name
        aging_map = {}
        for a in aging:
            props = a["properties"]
            entity = get_title(props, "Entry") or ""
            # Extract entity name (format: "AP - VendorName" or "AR - ClientName")
            name = entity.split(" - ")[-1] if " - " in entity else entity
            name_lower = name.lower()
            if name_lower not in aging_map:
                aging_map[name_lower] = []
            aging_map[name_lower].append({
                "balance": get_number(props, "Outstanding Balance") or 0,
                "bucket": get_select(props, "Aging Bucket") or "Current",
                "status": get_select(props, "Status") or "Open",
            })

        for v in vendors:
            props = v["properties"]
            name = get_title(props, "Vendor Name")
            spend = get_number(props, "Annual Spend") or 0
            otd = get_number(props, "On-Time Delivery") or 0
            risk = get_select(props, "Risk Rating") or "Medium"
            quality = get_select(props, "Quality Score") or "C (70-84)"
            status = get_select(props, "Status") or "Active"
            tier = get_select(props, "Strategic Priority") or "Tier 3 - Commodity"
            contract_end = get_date(props, "Contract End Date")

            risk_score = self._calculate_risk_score(otd, quality, risk, status)

            # Check aging for this vendor
            vendor_aging = aging_map.get(name.lower(), [])
            overdue_balance = sum(
                a["balance"] for a in vendor_aging
                if a["status"] in ("Overdue", "Disputed")
            )

            # Risk assessment
            risk_changed = False
            new_risk = risk

            if risk_score >= 75:
                new_risk = "Critical"
                risk_changed = True
            elif risk_score >= 55:
                new_risk = "High"
                risk_changed = True
            elif risk_score >= 30:
                new_risk = "Medium"
                risk_changed = new_risk != risk
            elif risk_score >= 15:
                new_risk = "Medium"
                risk_changed = new_risk != risk
            else:
                new_risk = "Low"
                risk_changed = new_risk != risk

            # Contract expiry warning (within 90 days)
            if contract_end:
                try:
                    end = datetime.strptime(contract_end, "%Y-%m-%d")
                    days_left = (end - today).days
                    if 0 < days_left <= 90:
                        contract_warnings.append({
                            "vendor": name,
                            "days_left": days_left,
                            "tier": tier,
                            "spend": spend,
                            "page_id": v["id"],
                        })
                except ValueError:
                    pass

            entry = {
                "vendor": name,
                "spend": spend,
                "otd": otd,
                "quality": quality,
                "risk_score": risk_score,
                "current_risk": risk,
                "new_risk": new_risk,
                "risk_changed": risk_changed,
                "tier": tier,
                "overdue_balance": overdue_balance,
                "status": status,
                "page_id": v["id"],
            }

            if new_risk in ("High", "Critical"):
                at_risk.append(entry)
                total_spend_at_risk += spend

            if otd >= 0.93 and quality in ("A (95-100)", "B (85-94)"):
                high_performers.append(entry)

        # Sort at-risk by spend descending
        at_risk.sort(key=lambda x: x["spend"], reverse=True)
        contract_warnings.sort(key=lambda x: x["days_left"])

        return {
            "total_vendors": len(vendors),
            "at_risk": at_risk,
            "at_risk_count": len(at_risk),
            "total_spend_at_risk": total_spend_at_risk,
            "contract_warnings": contract_warnings,
            "contract_warnings_count": len(contract_warnings),
            "high_performers": high_performers,
        }

    def _calculate_risk_score(self, otd: float, quality: str,
                               current_risk: str, status: str) -> float:
        """Calculate composite risk score (0-100, higher = more risky)."""
        score = 0.0

        # On-time delivery risk (0-30 points)
        if otd < 0.80:
            score += 30
        elif otd < 0.85:
            score += 25
        elif otd < 0.90:
            score += 20
        elif otd < 0.95:
            score += 10
        else:
            score += 0

        # Quality risk (0-25 points)
        quality_scores = {
            "A (95-100)": 0, "B (85-94)": 10,
            "C (70-84)": 20, "D (Below 70)": 25,
        }
        score += quality_scores.get(quality, 15)

        # Status risk (0-25 points)
        status_scores = {
            "Active": 0, "Under Review": 15,
            "On Notice": 22, "Terminated": 25,
        }
        score += status_scores.get(status, 10)

        # Existing risk baseline (0-20 points)
        risk_scores = {"Low": 0, "Medium": 8, "High": 15, "Critical": 20}
        score += risk_scores.get(current_risk, 5)

        return score

    # ── Write Back ──────────────────────────────────────────────────────

    def _update_risk_ratings(self, analysis: dict):
        """Update vendor risk ratings where changes detected."""
        updates = 0
        for v in analysis["at_risk"]:
            if v["risk_changed"]:
                self.client.update_page(v["page_id"], {
                    "Risk Rating": {"select": {"name": v["new_risk"]}},
                })
                updates += 1
                logger.info(f"Updated {v['vendor']} risk: {v['current_risk']} -> {v['new_risk']}")
        logger.info(f"Updated {updates} vendor risk ratings")

    def _write_alerts(self, analysis: dict):
        """Append vendor risk alerts to CFO page."""
        blocks = [
            {"object": "block", "type": "divider", "divider": {}},
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": to_rich_text("Vendor Risk Alert Report")}},
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": to_rich_text(
                 f"Total vendors: {analysis['total_vendors']} | "
                 f"At-risk: {analysis['at_risk_count']} | "
                 f"Spend at risk: ${analysis['total_spend_at_risk']:,.0f} | "
                 f"Contract renewals (90d): {analysis['contract_warnings_count']}"
             )}},
        ]

        if analysis["at_risk"]:
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": to_rich_text("At-Risk Vendors")}},
            )
            for v in analysis["at_risk"]:
                emoji = "🔴" if v["new_risk"] == "Critical" else "🟠"
                blocks.append({
                    "object": "block", "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": to_rich_text(
                            f"{emoji} {v['vendor']} — Risk Score: {v['risk_score']:.0f}/100, "
                            f"OTD: {v['otd']:.0%}, Quality: {v['quality']}, "
                            f"Spend: ${v['spend']:,.0f}, Tier: {v['tier']}"
                        )
                    }
                })

        if analysis["contract_warnings"]:
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": to_rich_text("Contract Renewal Warnings")}},
            )
            for w in analysis["contract_warnings"]:
                blocks.append({
                    "object": "block", "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": to_rich_text(
                            f"📅 {w['vendor']} — {w['days_left']} days to expiry, "
                            f"Tier: {w['tier']}, Annual Spend: ${w['spend']:,.0f}. "
                            f"Initiate renewal or RFP process immediately."
                        )
                    }
                })

        if analysis["high_performers"]:
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": to_rich_text("Top Performers")}},
            )
            for h in analysis["high_performers"]:
                blocks.append({
                    "object": "block", "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": to_rich_text(
                            f"⭐ {h['vendor']} — OTD: {h['otd']:.0%}, "
                            f"Quality: {h['quality']}. Consider for volume increase."
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
        logger.info("Vendor risk alerts written to CFO page")
