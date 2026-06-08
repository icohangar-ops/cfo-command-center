"""
CFO Command Center — Oracle Cloud ERP Connector

Connects to Oracle Cloud ERP via REST API for financial data extraction.

Authentication: OAuth 2.0 Client Credentials or Basic Auth
API: Oracle Fusion Applications REST API

Endpoints:
  - Vendors:    /fscmRestApi/resources/11.13.18.05/suppliers
  - Invoices:   /fscmRestApi/resources/11.13.18.05/invoices
  - Payments:   /fscmRestApi/resources/11.13.18.05/payments
  - GL:         /fscmRestApi/resources/11.13.18.05/journalEntries
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from ..base import BaseConnector, ConnectorConfig

logger = logging.getLogger("connector.oracle")


class OracleConnector(BaseConnector):
    """Oracle Cloud ERP REST API connector for financial data extraction."""

    # Oracle Fusion Apps REST endpoints
    REST_SUPPLIERS = "/fscmRestApi/resources/11.13.18.05/suppliers"
    REST_INVOICES = "/fscmRestApi/resources/11.13.18.05/invoices"
    REST_PAYMENTS = "/fscmRestApi/resources/11.13.18.05/payments"
    REST_GL = "/fscmRestApi/resources/11.13.18.05/journalEntries"

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.base_url = (config.base_url or "").rstrip("/")
        self.business_unit = config.company_id or ""
        self._auth_header = None

    def connect(self) -> bool:
        """Establish Oracle Cloud ERP connection."""
        if not self.base_url:
            self.logger.error("Oracle base_url not configured")
            return False

        if self.config.token:
            self._auth_header = f"Bearer {self.config.token}"
        elif self.config.username and self.config.password:
            import base64
            credentials = f"{self.config.username}:{self.config.password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            self._auth_header = f"Basic {encoded}"
        else:
            self.logger.error("No Oracle credentials configured")
            return False

        try:
            health = self.health_check()
            if health.get("status") == "ok":
                self._connected = True
                self.logger.info(f"Connected to Oracle ERP at {self.base_url}")
                return True
        except Exception as e:
            self.logger.error(f"Oracle connection failed: {e}")
        return False

    def disconnect(self) -> None:
        self._connected = False
        self._auth_header = None

    def health_check(self) -> dict:
        try:
            url = f"{self.base_url}/fscmRestApi/resources/11.13.18.05/"
            headers = {"Authorization": self._auth_header} if self._auth_header else {}
            req = Request(url, headers=headers, method="GET")
            with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                return {"status": "ok", "system": "Oracle Cloud ERP", "url": self.base_url}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _rest_get(self, path: str, params: Optional[dict] = None,
                  limit: int = 100) -> list[dict]:
        """Execute a REST GET request with pagination."""
        import urllib.parse

        query_params = params or {}
        query_params["limit"] = str(limit)
        query_params["offset"] = "0"

        all_results = []
        offset = 0

        while True:
            query_params["offset"] = str(offset)
            qs = urllib.parse.urlencode(query_params)
            url = f"{self.base_url}{path}?{qs}"

            headers = {"Authorization": self._auth_header} if self._auth_header else {}
            headers["Accept"] = "application/json"
            req = Request(url, headers=headers, method="GET")

            try:
                with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    data = json.loads(resp.read().decode())

                items = data.get("items", data.get("data", []))
                all_results.extend(items)

                if len(items) < limit:
                    break
                offset += limit

            except HTTPError as e:
                self.logger.error(f"Oracle HTTP {e.code}: {e.read().decode()[:200]}")
                raise
            except (URLError, Exception) as e:
                self.logger.error(f"Oracle REST request failed: {e}")
                raise

        return all_results

    def extract_vendors(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting suppliers from Oracle ERP...")
        params = {"q": f"ActiveFlag eq 'Y'"}
        if self.business_unit:
            params["q"] += f" and BusinessUnit eq '{self.business_unit}'"

        results = self._rest_get(self.REST_SUPPLIERS, params=params,
                                 limit=self.config.batch_size)
        suppliers = []
        for r in results:
            suppliers.append({
                "LIFNR": r.get("SupplierNumber", ""),
                "NAME1": r.get("SupplierName", ""),
                "KTOKK": r.get("SupplierType", ""),
                "BUKRS": r.get("BusinessUnit", self.business_unit),
                "WAERS": r.get("Currency", self.config.extra_params.get("default_currency", "USD")),
            })
        self.logger.info(f"Extracted {len(suppliers)} suppliers")
        return suppliers

    def extract_invoices(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting invoices from Oracle ERP...")
        days_back = kwargs.get("days_back", 90)
        cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        params = {"q": f"InvoiceDate ge '{cutoff}'"}

        results = self._rest_get(self.REST_INVOICES, params=params,
                                 limit=self.config.batch_size)
        invoices = []
        for r in results:
            invoices.append({
                "BELNR": r.get("InvoiceNumber", ""),
                "LIFNR": r.get("Supplier", ""),
                "BUDAT": r.get("InvoiceDate", ""),
                "WRBTR": r.get("InvoiceAmount", 0),
                "WAERS": r.get("Currency", "USD"),
                "BUKRS": r.get("BusinessUnit", self.business_unit),
                "SHKZG": "S" if (r.get("InvoiceAmount", 0) or 0) >= 0 else "H",
            })
        self.logger.info(f"Extracted {len(invoices)} invoices")
        return invoices

    def extract_payments(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting payments from Oracle ERP...")
        results = self._rest_get(self.REST_PAYMENTS, limit=self.config.batch_size)
        payments = []
        for r in results:
            payments.append({
                "BELNR": r.get("PaymentNumber", ""),
                "LIFNR": r.get("SupplierSite", ""),
                "BUDAT": r.get("PaymentDate", ""),
                "WRBTR": r.get("PaymentAmount", 0),
                "WAERS": r.get("Currency", "USD"),
                "BUKRS": r.get("BusinessUnit", self.business_unit),
            })
        self.logger.info(f"Extracted {len(payments)} payments")
        return payments

    def extract_general_ledger(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting GL entries from Oracle ERP...")
        days_back = kwargs.get("days_back", 30)
        cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        params = {"q": f"JournalEntryDate ge '{cutoff}'"}

        results = self._rest_get(self.REST_GL, params=params,
                                 limit=self.config.batch_size)
        gl_entries = []
        for r in results:
            gl_entries.append({
                "HKONT": r.get("AccountNumber", ""),
                "BUDAT": r.get("JournalEntryDate", ""),
                "PERIOD": r.get("AccountingPeriod", ""),
                "DMBTR": abs(r.get("EnteredAmount", 0) or 0),
                "WAERS": r.get("Currency", "USD"),
                "SHKZG": "S" if (r.get("EnteredAmount", 0) or 0) >= 0 else "H",
                "BUKRS": r.get("BusinessUnit", self.business_unit),
                "BLART": r.get("JournalCategory", ""),
            })
        self.logger.info(f"Extracted {len(gl_entries)} GL entries")
        return gl_entries
