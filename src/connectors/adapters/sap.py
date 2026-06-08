"""
CFO Command Center — SAP S/4HANA Connector

Connects to SAP S/4HANA via OData v4 API for extracting
financial data: vendors, invoices, payments, and GL entries.

Authentication: OAuth 2.0 Client Credentials or Basic Auth
API: OData v4 (SAP Gateway / SAP Business Hub)

Endpoints:
  - Vendors:    /sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner
  - Invoices:   /sap/opu/odata/sap/API_OData_V2_INVOICE/InvoiceHeader
  - Payments:   /sap/opu/odata/sap/API_JOURNAL_ENTRY/JournalEntry
  - GL:         /sap/opu/odata/sap/API_GL_ACCOUNT_LINE_ITEM/A_GLAccountLineItem
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from ..base import BaseConnector, ConnectorConfig

logger = logging.getLogger("connector.sap")


class SAPConnector(BaseConnector):
    """SAP S/4HANA OData API connector for financial data extraction."""

    # SAP OData service paths
    ODATA_VENDORS = "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner"
    ODATA_INVOICES = "/sap/opu/odata/sap/API_OData_V2_INVOICE/InvoiceHeader"
    ODATA_PAYMENTS = "/sap/opu/odata/sap/API_JOURNAL_ENTRY/JournalEntry"
    ODATA_GL = "/sap/opu/odata/sap/API_GL_ACCOUNT_LINE_ITEM/A_GLAccountLineItem"

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.base_url = (config.base_url or "").rstrip("/")
        self.company_code = config.company_id or ""
        self._auth_header = None

    def connect(self) -> bool:
        """Establish SAP OData connection with authentication."""
        if not self.base_url:
            self.logger.error("SAP base_url not configured")
            return False

        # Build auth header
        if self.config.token:
            self._auth_header = f"Bearer {self.config.token}"
        elif self.config.username and self.config.password:
            import base64
            credentials = f"{self.config.username}:{self.config.password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            self._auth_header = f"Basic {encoded}"
        else:
            self.logger.error("No SAP credentials configured (token or username/password)")
            return False

        # Test connectivity
        try:
            health = self.health_check()
            if health.get("status") == "ok":
                self._connected = True
                self.logger.info(f"Connected to SAP at {self.base_url}")
                return True
            else:
                self.logger.error(f"SAP health check failed: {health}")
                return False
        except Exception as e:
            self.logger.error(f"SAP connection test failed: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from SAP."""
        self._connected = False
        self._auth_header = None
        self.logger.info("Disconnected from SAP")

    def health_check(self) -> dict:
        """Check SAP OData connectivity."""
        try:
            url = f"{self.base_url}/sap/opu/odata/sap/API_BUSINESS_PARTNER/$metadata"
            headers = {"Authorization": self._auth_header} if self._auth_header else {}
            req = Request(url, headers=headers, method="GET")
            with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                return {
                    "status": "ok",
                    "system": "SAP S/4HANA",
                    "url": self.base_url,
                    "company_code": self.company_code,
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _odata_query(self, path: str, filters: Optional[str] = None,
                     select: Optional[str] = None, top: int = 100,
                     expand: Optional[str] = None) -> list[dict]:
        """Execute an OData GET request with query parameters."""
        params = [f"$top={top}", "$format=json"]
        if filters:
            params.append(f"$filter={filters}")
        if select:
            params.append(f"$select={select}")
        if expand:
            params.append(f"$expand={expand}")

        query_string = "&".join(params)
        url = f"{self.base_url}{path}?{query_string}"

        headers = {"Authorization": self._auth_header} if self._auth_header else {}
        headers["Accept"] = "application/json"

        all_results = []
        skip = 0

        while True:
            paginated_url = f"{url}&$skip={skip}"
            req = Request(paginated_url, headers=headers, method="GET")

            try:
                with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    data = json.loads(resp.read().decode())

                # OData v4 returns results in "value" array
                results = data.get("value", [])
                all_results.extend(results)

                # Check for more pages
                if len(results) < top:
                    break
                skip += top

            except HTTPError as e:
                error_body = e.read().decode() if e.fp else ""
                self.logger.error(f"OData HTTP {e.code}: {error_body[:200]}")
                raise
            except (URLError, Exception) as e:
                self.logger.error(f"OData request failed: {e}")
                raise

        return all_results

    # ── Data Extraction Methods ──────────────────────────────────────

    def extract_vendors(self, **kwargs) -> list[dict]:
        """
        Extract vendor master data from SAP Business Partner API.

        Returns:
            List of vendor dicts with SAP field names:
            LIFNR (vendor ID), NAME1 (name), BUKRS (company), WAERS (currency), etc.
        """
        self.logger.info("Extracting vendors from SAP...")

        # Filter for vendors (Business Partner Type = Organization)
        filters = "BusinessPartnerIsBlocked eq 'false'"
        if self.company_code:
            filters += f" and CompanyCode eq '{self.company_code}'"

        select = "BusinessPartner,FirstName,LastName,OrganizationBPName1,OrganizationBPName2,BusinessPartnerGroup,BusinessPartnerType,CreationDate,LastChangeDate"

        try:
            results = self._odata_query(
                self.ODATA_VENDORS,
                filters=filters,
                select=select,
                top=self.config.batch_size,
            )

            # Map SAP fields to readable names
            vendors = []
            for r in results:
                vendors.append({
                    "LIFNR": r.get("BusinessPartner", ""),
                    "NAME1": r.get("OrganizationBPName1", "") or r.get("FirstName", "") + " " + r.get("LastName", ""),
                    "NAME2": r.get("OrganizationBPName2", ""),
                    "KTOKK": r.get("BusinessPartnerGroup", ""),
                    "BUKRS": self.company_code,
                    "WAERS": self.config.extra_params.get("default_currency", "USD"),
                })

            self.logger.info(f"Extracted {len(vendors)} vendors")
            return vendors

        except Exception as e:
            self.logger.error(f"Vendor extraction failed: {e}")
            raise

    def extract_invoices(self, **kwargs) -> list[dict]:
        """
        Extract AP/AR invoice data from SAP.

        Returns:
            List of invoice dicts with SAP field names.
        """
        self.logger.info("Extracting invoices from SAP...")

        filters = ""
        if self.company_code:
            filters += f"CompanyCode eq '{self.company_code}'"

        # Optional date range
        days_back = kwargs.get("days_back", 90)
        if days_back:
            cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            if filters:
                filters += f" and PostingDate ge '{cutoff}'"
            else:
                filters += f"PostingDate ge '{cutoff}'"

        select = "CompanyCode,FiscalYear,AccountingDocumentType,DocumentDate,PostingDate,Supplier,AmountInTransactionCurrency,TransactionCurrency,ClearingDocument,IsCleared"

        try:
            results = self._odata_query(
                self.ODATA_INVOICES,
                filters=filters if filters else None,
                select=select,
                top=self.config.batch_size,
            )

            invoices = []
            for r in results:
                invoices.append({
                    "BELNR": r.get("AccountingDocumentType", "") + r.get("FiscalYear", ""),
                    "LIFNR": r.get("Supplier", ""),
                    "BUDAT": r.get("PostingDate", ""),
                    "BLDAT": r.get("DocumentDate", ""),
                    "WRBTR": r.get("AmountInTransactionCurrency", 0),
                    "WAERS": r.get("TransactionCurrency", "USD"),
                    "BUKRS": r.get("CompanyCode", self.company_code),
                    "AUGBL": r.get("ClearingDocument", ""),
                    "SHKZG": "S" if (r.get("AmountInTransactionCurrency", 0) or 0) >= 0 else "H",
                    "IS_CLEARED": r.get("IsCleared", False),
                })

            self.logger.info(f"Extracted {len(invoices)} invoices")
            return invoices

        except Exception as e:
            self.logger.error(f"Invoice extraction failed: {e}")
            raise

    def extract_payments(self, **kwargs) -> list[dict]:
        """Extract payment records from SAP Journal Entry API."""
        self.logger.info("Extracting payments from SAP...")

        filters = f"CompanyCode eq '{self.company_code}'" if self.company_code else ""
        days_back = kwargs.get("days_back", 30)
        if days_back:
            cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            filters += f" and PostingDate ge '{cutoff}'" if filters else f"PostingDate ge '{cutoff}'"

        select = "CompanyCode,AccountingDocumentType,FiscalYear,DocumentDate,PostingDate,Supplier,CashDiscountAmount,AmountInCompanyCodeCurrency,CompanyCodeCurrency"

        try:
            results = self._odata_query(
                self.ODATA_PAYMENTS,
                filters=filters if filters else None,
                select=select,
                top=self.config.batch_size,
            )

            payments = []
            for r in results:
                payments.append({
                    "BELNR": r.get("AccountingDocumentType", "") + r.get("FiscalYear", ""),
                    "LIFNR": r.get("Supplier", ""),
                    "BUDAT": r.get("PostingDate", ""),
                    "BLDAT": r.get("DocumentDate", ""),
                    "WRBTR": r.get("AmountInCompanyCodeCurrency", 0),
                    "WAERS": r.get("CompanyCodeCurrency", "USD"),
                    "BUKRS": r.get("CompanyCode", self.company_code),
                    "CASH_DISCOUNT": r.get("CashDiscountAmount", 0),
                })

            self.logger.info(f"Extracted {len(payments)} payments")
            return payments

        except Exception as e:
            self.logger.error(f"Payment extraction failed: {e}")
            raise

    def extract_general_ledger(self, **kwargs) -> list[dict]:
        """Extract GL line items from SAP."""
        self.logger.info("Extracting GL entries from SAP...")

        filters = ""
        if self.company_code:
            filters += f"CompanyCode eq '{self.company_code}'"

        days_back = kwargs.get("days_back", 30)
        if days_back:
            cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            filters += f" and PostingDate ge '{cutoff}'" if filters else f"PostingDate ge '{cutoff}'"

        select = "CompanyCode,GLAccount,PostingDate,FiscalYearPeriod,AmountInCompanyCodeCurrency,CompanyCodeCurrency,DebitCreditCode,AccountingDocumentType,ProfitCenter"

        try:
            results = self._odata_query(
                self.ODATA_GL,
                filters=filters if filters else None,
                select=select,
                top=self.config.batch_size,
            )

            gl_entries = []
            for r in results:
                gl_entries.append({
                    "HKONT": r.get("GLAccount", ""),
                    "BUDAT": r.get("PostingDate", ""),
                    "PERIOD": r.get("FiscalYearPeriod", ""),
                    "DMBTR": abs(r.get("AmountInCompanyCodeCurrency", 0) or 0),
                    "WAERS": r.get("CompanyCodeCurrency", "USD"),
                    "SHKZG": r.get("DebitCreditCode", "S"),
                    "BUKRS": r.get("CompanyCode", self.company_code),
                    "BLART": r.get("AccountingDocumentType", ""),
                    "PRCTR": r.get("ProfitCenter", ""),
                })

            self.logger.info(f"Extracted {len(gl_entries)} GL entries")
            return gl_entries

        except Exception as e:
            self.logger.error(f"GL extraction failed: {e}")
            raise
