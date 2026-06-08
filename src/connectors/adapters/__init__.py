"""
CFO Command Center — Connector Factory

Creates connector instances from configuration.
Centralizes connector creation and prevents code duplication.
"""

import logging
from typing import Optional

from ..base import BaseConnector, ConnectorConfig, ConnectorType

logger = logging.getLogger("connector.factory")


def create_connector(config: ConnectorConfig) -> BaseConnector:
    """
    Create a connector instance from its configuration.

    Args:
        config: ConnectorConfig with type, credentials, and settings

    Returns:
        Instantiated connector ready for connect()

    Raises:
        ValueError: If connector type is not supported
    """
    connector_map = {
        ConnectorType.SAP: _create_sap,
        ConnectorType.ORACLE: _create_oracle,
        ConnectorType.QUICKBOOKS: _create_quickbooks,
        ConnectorType.NETSUITE: _create_netsuite,
        ConnectorType.CSV: _create_csv,
        ConnectorType.CUSTOM: _create_custom,
    }

    factory_fn = connector_map.get(config.connector_type)
    if not factory_fn:
        raise ValueError(
            f"Unsupported connector type: {config.connector_type.value}. "
            f"Supported: {[t.value for t in ConnectorType]}"
        )

    logger.info(f"Creating {config.connector_type.value} connector: {config.name}")
    return factory_fn(config)


def _create_sap(config: ConnectorConfig) -> BaseConnector:
    from .sap import SAPConnector
    return SAPConnector(config)


def _create_oracle(config: ConnectorConfig) -> BaseConnector:
    from .oracle import OracleConnector
    return OracleConnector(config)


def _create_quickbooks(config: ConnectorConfig) -> BaseConnector:
    from .quickbooks import QuickBooksConnector
    return QuickBooksConnector(config)


def _create_netsuite(config: ConnectorConfig) -> BaseConnector:
    from .netsuite import NetSuiteConnector
    return NetSuiteConnector(config)


def _create_csv(config: ConnectorConfig) -> BaseConnector:
    from .csv_connector import CSVConnector
    return CSVConnector(config)


def _create_custom(config: ConnectorConfig) -> BaseConnector:
    """Create a generic REST API connector for custom integrations."""
    from .rest import RESTConnector
    return RESTConnector(config)


def list_supported_connectors() -> list[dict]:
    """Return information about all supported connector types."""
    return [
        {
            "type": ConnectorType.SAP.value,
            "name": "SAP S/4HANA",
            "description": "Connect to SAP S/4HANA via OData API for vendor, invoice, payment, and GL data extraction.",
            "auth": "OAuth 2.0 / Basic Auth",
            "protocols": ["OData v4", "RFC/BAPI"],
            "data_objects": ["vendors", "invoices", "payments", "general_ledger"],
        },
        {
            "type": ConnectorType.ORACLE.value,
            "name": "Oracle Cloud ERP",
            "description": "Connect to Oracle Cloud ERP via REST API for financial data extraction.",
            "auth": "OAuth 2.0 / Basic Auth",
            "protocols": ["REST API", "SOAP"],
            "data_objects": ["vendors", "invoices", "payments", "general_ledger"],
        },
        {
            "type": ConnectorType.QUICKBOOKS.value,
            "name": "QuickBooks Online",
            "description": "Connect to QuickBooks Online via Intuit Data Services API.",
            "auth": "OAuth 2.0",
            "protocols": ["REST API"],
            "data_objects": ["vendors", "invoices", "payments", "general_ledger"],
        },
        {
            "type": ConnectorType.NETSUITE.value,
            "name": "NetSuite",
            "description": "Connect to NetSuite via SuiteTalk REST Web Services.",
            "auth": "OAuth 2.0 / Token-based",
            "protocols": ["SuiteTalk REST", "SOAP"],
            "data_objects": ["vendors", "invoices", "payments", "general_ledger"],
        },
        {
            "type": ConnectorType.CSV.value,
            "name": "CSV / Flat File",
            "description": "Import data from CSV files with configurable field mappings.",
            "auth": "None (file-based)",
            "protocols": ["File System", "S3", "GCS"],
            "data_objects": ["vendors", "invoices", "payments", "general_ledger"],
        },
        {
            "type": ConnectorType.CUSTOM.value,
            "name": "Custom REST API",
            "description": "Connect to any REST API endpoint with configurable field mappings.",
            "auth": "API Key / Bearer Token / Basic Auth",
            "protocols": ["REST API"],
            "data_objects": ["vendors", "invoices", "payments", "general_ledger"],
        },
    ]
