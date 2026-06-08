"""
CFO Command Center — NetSuite Connector

Connects to NetSuite via SuiteTalk REST Web Services.

Authentication: OAuth 2.0 / Token-based Authentication
API: SuiteTalk REST (preferred) or SOAP

Endpoints (REST):
  - Vendors:    /rest/v1.0/vendor
  - Invoices:   /rest/v1.0/invoice
  - Payments:   /rest/v1.0/vendorPayment
  - GL:         /rest/v1.0/generalLedgerAccount
"""

import logging
import json
from datetime import datetime
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from ..base import BaseConnector, ConnectorConfig

logger = logging.getLogger("connector.netsuite")


class NetSuiteConnector(BaseConnector):
    """NetSuite SuiteTalk REST connector for financial data extraction."""

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.base_url = (config.base_url or "").rstrip("/")
        self.account_id = config.realm or ""
        self.subsidiary = config.company_id or ""
        self._auth_header = None

    def connect(self) -> bool:
        if not self.base_url:
            self.base_url = f"https://{self.account_id}.suitetalk.api.netsuite.com"

        if not self.account_id:
            self.logger.error("NetSuite account ID (realm) not configured")
            return False

        if self.config.token:
            self._auth_header = f"Bearer {self.config.token}"
        elif self.config.api_key:
            self._auth_header = f"NLAuth nlauth_account={self.account_id}, nlauth_email={self.config.username or ''}, nlauth_signature={self.config.password or ''}, nlauth_role=3"
        else:
            self.logger.error("NetSuite credentials not configured")
            return False

        try:
            health = self.health_check()
            if health.get("status") == "ok":
                self._connected = True
                self.logger.info(f"Connected to NetSuite ({self.account_id})")
                return True
        except Exception as e:
            self.logger.error(f"NetSuite connection failed: {e}")
        return False

    def disconnect(self) -> None:
        self._connected = False
        self._auth_header = None

    def health_check(self) -> dict:
        try:
            url = f"{self.base_url}/rest/v1.0/statistics"
            headers = {"Authorization": self._auth_header, "Accept": "application/json"}
            req = Request(url, headers=headers, method="GET")
            with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                return {"status": "ok", "system": "NetSuite", "account": self.account_id}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _ns_rest_get(self, path: str, params: Optional[dict] = None) -> list[dict]:
        """Execute a SuiteTalk REST GET request with pagination."""
        import urllib.parse

        query_params = params or {}
        query_params["limit"] = str(self.config.batch_size)

        all_results = []
        offset = 0

        while True:
            query_params["offset"] = str(offset)
            qs = urllib.parse.urlencode(query_params)
            url = f"{self.base_url}/rest/v1.0{path}?{qs}"

            headers = {"Authorization": self._auth_header, "Accept": "application/json"}
            req = Request(url, headers=headers, method="GET")

            try:
                with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    data = json.loads(resp.read().decode())

                items = data.get("items", data.get("count", []))
                if isinstance(items, dict):
                    items = [items]
                all_results.extend(items)

                count = data.get("totalResults", len(items))
                if offset + self.config.batch_size >= count:
                    break
                offset += self.config.batch_size

            except HTTPError as e:
                self.logger.error(f"NetSuite HTTP {e.code}: {e.read().decode()[:200]}")
                raise
            except (URLError, Exception) as e:
                self.logger.error(f"NetSuite request failed: {e}")
                raise

        return all_results

    def extract_vendors(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting vendors from NetSuite...")
        params = {}
        if self.subsidiary:
            params["subsidiary"] = f"is {self.subsidiary}"

        results = self._ns_rest_get("/vendor", params=params)
        vendors = []
        for r in results:
            vendor_name = r.get("companyname", r.get("entityid", ""))
            vendors.append({
                "LIFNR": r.get("internalid", ""),
                "NAME1": vendor_name,
                "BUKRS": r.get("subsidiary", self.subsidiary),
                "WAERS": r.get("currency", self.config.extra_params.get("default_currency", "USD")),
                "ZTERM": r.get("terms", ""),
                "KTOKK": r.get("category", ""),
            })
        self.logger.info(f"Extracted {len(vendors)} vendors")
        return vendors

    def extract_invoices(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting invoices from NetSuite...")
        results = self._ns_rest_get("/invoice")
        invoices = []
        for r in results:
            invoices.append({
                "BELNR": r.get("tranid", ""),
                "LIFNR": r.get("entity", {}).get("display", "") if isinstance(r.get("entity"), dict) else r.get("entity", ""),
                "BUDAT": r.get("trandate", ""),
                "WRBTR": abs(r.get("total", 0) or 0),
                "WAERS": r.get("currency", "USD"),
                "BUKRS": r.get("subsidiary", self.subsidiary),
            })
        self.logger.info(f"Extracted {len(invoices)} invoices")
        return invoices

    def extract_payments(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting payments from NetSuite...")
        results = self._ns_rest_get("/vendorPayment")
        payments = []
        for r in results:
            payments.append({
                "BELNR": r.get("internalid", ""),
                "LIFNR": r.get("entity", ""),
                "BUDAT": r.get("trandate", ""),
                "WRBTR": abs(r.get("payment", 0) or 0),
                "WAERS": r.get("currency", "USD"),
                "BUKRS": r.get("subsidiary", self.subsidiary),
            })
        self.logger.info(f"Extracted {len(payments)} payments")
        return payments

    def extract_general_ledger(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting GL entries from NetSuite...")
        results = self._ns_rest_get("/generalLedgerAccount")
        gl_entries = []
        for r in results:
            gl_entries.append({
                "HKONT": r.get("accountNumber", r.get("internalid", "")),
                "BUDAT": r.get("lastModifiedDate", ""),
                "BUKRS": r.get("subsidiary", self.subsidiary),
                "WAERS": r.get("currency", "USD"),
                "KTOKS": r.get("type", ""),
            })
        self.logger.info(f"Extracted {len(gl_entries)} GL entries")
        return gl_entries
