"""
CFO Command Center — Generic REST API Connector

Connects to any REST API endpoint for financial data extraction.
Useful for custom/internal ERP systems that expose REST APIs.

Authentication: API Key / Bearer Token / Basic Auth
API: Any REST API (configurable endpoints and field mappings)

Configuration via extra_params:
    {
        "endpoints": {
            "vendors": {"path": "/api/vendors", "method": "GET", "response_key": "data"},
            "invoices": {"path": "/api/invoices", "method": "GET", "response_key": "data"},
            "payments": {"path": "/api/payments", "method": "GET", "response_key": "data"},
            "general_ledger": {"path": "/api/gl", "method": "GET", "response_key": "data"},
        },
        "headers": {"X-Custom-Header": "value"},
        "pagination": {"type": "offset", "page_param": "page", "size_param": "size"},
    }
"""

import logging
import json
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from ..base import BaseConnector, ConnectorConfig

logger = logging.getLogger("connector.rest")


class RESTConnector(BaseConnector):
    """Generic REST API connector for custom ERP integrations."""

    DEFAULT_ENDPOINTS = {
        "vendors": {"path": "/api/vendors", "response_key": "data"},
        "invoices": {"path": "/api/invoices", "response_key": "data"},
        "payments": {"path": "/api/payments", "response_key": "data"},
        "general_ledger": {"path": "/api/gl", "response_key": "data"},
    }

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.base_url = (config.base_url or "").rstrip("/")
        self.endpoints = config.extra_params.get("endpoints", self.DEFAULT_ENDPOINTS)
        self.custom_headers = config.extra_params.get("headers", {})
        self.pagination = config.extra_params.get("pagination", {})
        self._auth_header = None

    def connect(self) -> bool:
        if not self.base_url:
            self.logger.error("REST base_url not configured")
            return False

        if self.config.token:
            self._auth_header = f"Bearer {self.config.token}"
        elif self.config.api_key:
            self._auth_header = f"ApiKey {self.config.api_key}"
        elif self.config.username and self.config.password:
            import base64
            credentials = f"{self.config.username}:{self.config.password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            self._auth_header = f"Basic {encoded}"

        try:
            health = self.health_check()
            if health.get("status") == "ok":
                self._connected = True
                self.logger.info(f"Connected to REST API at {self.base_url}")
                return True
        except Exception as e:
            self.logger.error(f"REST connection failed: {e}")
        return False

    def disconnect(self) -> None:
        self._connected = False
        self._auth_header = None

    def health_check(self) -> dict:
        try:
            url = f"{self.base_url}/" if not self.base_url.endswith("/") else self.base_url
            headers = {**self.custom_headers}
            if self._auth_header:
                headers["Authorization"] = self._auth_header
            req = Request(url, headers=headers, method="GET")
            with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                return {"status": "ok", "system": "Custom REST API", "url": self.base_url}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _rest_get(self, dataset: str) -> list[dict]:
        """Execute a REST GET for a dataset and extract the response array."""
        endpoint = self.endpoints.get(dataset, {})
        path = endpoint.get("path", f"/api/{dataset}")
        response_key = endpoint.get("response_key", "data")

        url = f"{self.base_url}{path}"
        headers = {**self.custom_headers}
        if self._auth_header:
            headers["Authorization"] = self._auth_header
        headers["Accept"] = "application/json"

        req = Request(url, headers=headers, method="GET")

        try:
            with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                data = json.loads(resp.read().decode())

            # Navigate to the response key (supports nested keys like "data.items")
            keys = response_key.split(".")
            result = data
            for key in keys:
                if isinstance(result, dict):
                    result = result.get(key, [])
                else:
                    break

            if isinstance(result, list):
                return result
            elif isinstance(result, dict):
                return [result]
            return []

        except HTTPError as e:
            self.logger.error(f"REST HTTP {e.code}: {e.read().decode()[:200]}")
            raise
        except (URLError, Exception) as e:
            self.logger.error(f"REST request failed: {e}")
            raise

    def extract_vendors(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting vendors from REST API...")
        results = self._rest_get("vendors")
        self.logger.info(f"Extracted {len(results)} vendors")
        return results

    def extract_invoices(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting invoices from REST API...")
        results = self._rest_get("invoices")
        self.logger.info(f"Extracted {len(results)} invoices")
        return results

    def extract_payments(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting payments from REST API...")
        results = self._rest_get("payments")
        self.logger.info(f"Extracted {len(results)} payments")
        return results

    def extract_general_ledger(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting GL entries from REST API...")
        results = self._rest_get("general_ledger")
        self.logger.info(f"Extracted {len(results)} GL entries")
        return results
