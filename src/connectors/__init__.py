"""
CFO Command Center — ERP Connector Framework

Provides a unified interface for connecting to multiple ERP systems
and importing financial data into the CFO Command Center.

Connectors:
  - BaseConnector: Abstract base class for all ERP adapters
  - SAPConnector: SAP S/4HANA via OData API
  - OracleConnector: Oracle Cloud ERP via REST API
  - QuickBooksConnector: QuickBooks Online via Intuit API
  - NetSuiteConnector: NetSuite via SuiteTalk REST
  - CSVConnector: Universal flat file import (CSV/Excel)
  - NotionConnector: Bidirectional Notion database sync
  - Normalizer: Field mapping and data normalization layer
  - SyncPipeline: Incremental sync with audit trail
"""

from .base import BaseConnector, ConnectorConfig, SyncResult
from .normalizer import Normalizer, FieldMapping, ValidationResult
from .pipeline import SyncPipeline, SyncRecord

__all__ = [
    "BaseConnector", "ConnectorConfig", "SyncResult",
    "Normalizer", "FieldMapping", "ValidationResult",
    "SyncPipeline", "SyncRecord",
]
