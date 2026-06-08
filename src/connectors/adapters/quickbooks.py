"""
CFO Command Center — QuickBooks Online Connector

Connects to QuickBooks Online via Intuit Data Services API.

Authentication: OAuth 2.0 (Intuit authorization flow)
API: QuickBooks Online REST API v3

Endpoints:
  - Vendors:    /v3/company/{realm}/vendor
  - Invoices:   /v3/company/{realm}/invoice
  - Payments:   /v3/company/{realm}/payment
  - GL:         /v3/company/{realm}/query (Query API)
"""

import logging
import json
from datetime import datetime
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from ..base import BaseConnector, ConnectorConfig

logger = logging.getLogger("connector.quickbooks")


class QuickBooksConnector(BaseConnector):
    """QuickBooks Online API connector for financial data extraction."""

    API_BASE = "https://quickbooks.api.intuit.com"

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.realm = config.realm or ""
        self.base_url = config.base_url or self.API_BASE
        self._auth_header = None

    def connect(self) -> bool:
        if not self.realm:
            self.logger.error("QuickBooks realm (company ID) not configured")
            return False

        if self.config.token:
            self._auth_header = f"Bearer {self.config.token}"
        else:
            self.logger.error("QuickBooks OAuth token not configured")
            return False

        try:
            health = self.health_check()
            if health.get("status") == "ok":
                self._connected = True
                self.logger.info(f"Connected to QuickBooks (realm: {self.realm})")
                return True
        except Exception as e:
            self.logger.error(f"QuickBooks connection failed: {e}")
        return False

    def disconnect(self) -> None:
        self._connected = False
        self._auth_header = None

    def health_check(self) -> dict:
        try:
            url = f"{self.base_url}/v3/company/{self.realm}/companyinfo/{self.realm}"
            headers = {"Authorization": self._auth_header, "Accept": "application/json"}
            req = Request(url, headers=headers, method="GET")
            with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                data = json.loads(resp.read().decode())
                company = data.get("CompanyInfo", {})
                return {
                    "status": "ok",
                    "system": "QuickBooks Online",
                    "company_name": company.get("CompanyName", ""),
                    "realm": self.realm,
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _qbo_get(self, path: str) -> list[dict]:
        """Execute a QBO GET request."""
        url = f"{self.base_url}/v3/company/{self.realm}{path}"
        headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json",
        }
        req = Request(url, headers=headers, method="GET")

        try:
            with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                data = json.loads(resp.read().decode())
            return data  # QBO returns { "QueryResponse": {...}, "response": ... }
        except HTTPError as e:
            self.logger.error(f"QBO HTTP {e.code}: {e.read().decode()[:200]}")
            raise
        except (URLError, Exception) as e:
            self.logger.error(f"QBO request failed: {e}")
            raise

    def _qbo_query(self, query: str) -> list[dict]:
        """Execute a QBO Query API request."""
        import urllib.parse
        url = f"{self.base_url}/v3/company/{self.realm}/query?query={urllib.parse.quote(query)}"
        headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json",
        }
        req = Request(url, headers=headers, method="GET")

        try:
            with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                data = json.loads(resp.read().decode())
            return data.get("QueryResponse", {})
        except Exception as e:
            self.logger.error(f"QBO query failed: {e}")
            raise

    def extract_vendors(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting vendors from QuickBooks...")
        data = self._qbo_get("/vendor?query=Active IN (true, false)")
        vendors = data.get("QueryResponse", {}).get("Vendor", [])
        self.logger.info(f"Extracted {len(vendors)} vendors")
        return vendors

    def extract_invoices(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting invoices from QuickBooks...")
        data = self._qbo_get("/invoice")
        invoices = data.get("QueryResponse", {}).get("Invoice", [])
        self.logger.info(f"Extracted {len(invoices)} invoices")
        return invoices

    def extract_payments(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting payments from QuickBooks...")
        data = self._qbo_get("/payment")
        payments = data.get("QueryResponse", {}).get("Payment", [])
        self.logger.info(f"Extracted {len(payments)} payments")
        return payments

    def extract_general_ledger(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting GL entries from QuickBooks...")
        # QBO uses JournalEntry for GL-like data
        data = self._qbo_get("/journalentry")
        entries = data.get("QueryResponse", {}).get("JournalEntry", [])
        self.logger.info(f"Extracted {len(entries)} journal entries")
        return entries
