"""
CFO Command Center — Base Connector

Abstract base class for all ERP connector adapters.
Defines the standard interface for connecting, extracting,
and transforming financial data from external systems.

Each connector implements:
  1. connect() — authenticate and establish connection
  2. extract() — pull raw financial data from the source
  3. health_check() — verify connectivity
  4. disconnect() — clean up resources
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from enum import Enum

logger = logging.getLogger("connector.base")


class ConnectorType(str, Enum):
    """Supported ERP connector types."""
    SAP = "sap"
    ORACLE = "oracle"
    QUICKBOOKS = "quickbooks"
    NETSUITE = "netsuite"
    CSV = "csv"
    NOTION = "notion"
    CUSTOM = "custom"


class SyncStatus(str, Enum):
    """Status of a sync operation."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ConnectorConfig:
    """Configuration for an ERP connector instance."""
    connector_type: ConnectorType
    name: str
    entity_id: str  # Links to the entity this connector serves
    description: str = ""

    # Connection parameters (connector-specific)
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    realm: Optional[str] = None  # NetSuite account ID
    company_id: Optional[str] = None  # SAP company code / Oracle business unit

    # Sync parameters
    sync_frequency: str = "daily"  # daily, hourly, real-time, manual
    batch_size: int = 100
    timeout_seconds: int = 60
    retry_attempts: int = 3
    retry_delay_seconds: int = 5

    # Scope control
    enabled: bool = True
    last_sync: Optional[str] = None
    last_sync_status: Optional[str] = None

    # Additional connector-specific params
    extra_params: dict = field(default_factory=dict)

    def mask_secrets(self) -> dict:
        """Return config dict with secrets masked for logging."""
        d = {
            "connector_type": self.connector_type.value,
            "name": self.name,
            "entity_id": self.entity_id,
            "base_url": self.base_url,
            "enabled": self.enabled,
        }
        if self.api_key:
            d["api_key"] = self.api_key[:6] + "..." if len(self.api_key) > 6 else "***"
        if self.token:
            d["token"] = self.token[:6] + "..." if len(self.token) > 6 else "***"
        return d


@dataclass
class SyncResult:
    """Result of a connector sync operation."""
    connector_name: str
    entity_id: str
    status: SyncStatus
    records_extracted: int = 0
    records_transformed: int = 0
    records_written: int = 0
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        """Calculate the success rate of the sync."""
        if self.records_extracted == 0:
            return 0.0
        return (self.records_written / self.records_extracted) * 100.0

    def to_dict(self) -> dict:
        """Convert to dict for serialization."""
        return {
            "connector_name": self.connector_name,
            "entity_id": self.entity_id,
            "status": self.status.value,
            "records_extracted": self.records_extracted,
            "records_transformed": self.records_transformed,
            "records_written": self.records_written,
            "success_rate": round(self.success_rate, 1),
            "errors": self.errors[:10],
            "warnings": self.warnings[:10],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": round(self.duration_seconds, 2),
            "metadata": self.metadata,
        }


class BaseConnector(ABC):
    """
    Abstract base class for all ERP connectors.

    Lifecycle:
        connect() -> extract() -> transform() -> [repeat] -> disconnect()

    Usage:
        connector = SAPConnector(config)
        connector.connect()
        result = connector.extract_vendors()
        result = connector.extract_invoices()
        connector.disconnect()
    """

    def __init__(self, config: ConnectorConfig):
        self.config = config
        self._connected = False
        self._session = None
        self.logger = logging.getLogger(f"connector.{config.connector_type.value}")

    # ── Lifecycle ────────────────────────────────────────────────────

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to the ERP system."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection and clean up resources."""
        pass

    @abstractmethod
    def health_check(self) -> dict:
        """Check connectivity and return system health info."""
        pass

    # ── Data Extraction (standard financial objects) ─────────────────

    @abstractmethod
    def extract_vendors(self, **kwargs) -> list[dict]:
        """Extract vendor/supplier master data."""
        pass

    @abstractmethod
    def extract_invoices(self, **kwargs) -> list[dict]:
        """Extract AP/AR invoice data."""
        pass

    @abstractmethod
    def extract_payments(self, **kwargs) -> list[dict]:
        """Extract payment history."""
        pass

    @abstractmethod
    def extract_general_ledger(self, **kwargs) -> list[dict]:
        """Extract GL entries for working capital / cash flow analysis."""
        pass

    # ── Full Sync (template method pattern) ──────────────────────────

    def full_sync(self) -> SyncResult:
        """
        Execute a full data extraction across all financial objects.
        Returns a SyncResult with counts and errors.
        """
        start = datetime.now(timezone.utc)
        result = SyncResult(
            connector_name=self.config.name,
            entity_id=self.config.entity_id,
            status=SyncStatus.FAILED,
            started_at=start.isoformat(),
        )

        if not self._connected:
            self.logger.info("Not connected, attempting connect...")
            if not self.connect():
                result.errors.append("Failed to connect to ERP system")
                result.completed_at = datetime.now(timezone.utc).isoformat()
                return result

        try:
            # Extract all data objects
            datasets = {
                "vendors": self._safe_extract("extract_vendors"),
                "invoices": self._safe_extract("extract_invoices"),
                "payments": self._safe_extract("extract_payments"),
                "general_ledger": self._safe_extract("extract_general_ledger"),
            }

            total_extracted = 0
            total_transformed = 0
            all_transformed = []

            for name, records in datasets.items():
                if records is None:
                    result.warnings.append(f"No data extracted for {name}")
                    continue
                total_extracted += len(records)
                transformed = self._transform_records(name, records)
                total_transformed += len(transformed)
                all_transformed.append((name, transformed))

            result.records_extracted = total_extracted
            result.records_transformed = total_transformed
            result.records_written = total_transformed
            result.metadata["datasets"] = {
                name: len(records) for name, records in datasets.items()
                if records is not None
            }

            if total_extracted > 0:
                result.status = SyncStatus.SUCCESS if len(result.errors) == 0 else SyncStatus.PARTIAL
            else:
                result.status = SyncStatus.SKIPPED
                result.warnings.append("No records extracted from any data source")

        except Exception as e:
            self.logger.error(f"Full sync failed: {e}", exc_info=True)
            result.errors.append(str(e))
        finally:
            end = datetime.now(timezone.utc)
            result.completed_at = end.isoformat()
            result.duration_seconds = (end - start).total_seconds()

        self.logger.info(
            f"Full sync complete: {result.status.value}, "
            f"{result.records_extracted} extracted, "
            f"{result.records_written} written in {result.duration_seconds:.1f}s"
        )
        return result

    def _safe_extract(self, method_name: str, **kwargs) -> Optional[list[dict]]:
        """Safely call an extract method and handle errors."""
        try:
            method = getattr(self, method_name)
            return method(**kwargs)
        except NotImplementedError:
            self.logger.warning(f"Method {method_name} not implemented by {type(self).__name__}")
            return None
        except Exception as e:
            self.logger.error(f"Error in {method_name}: {e}")
            return []

    def _transform_records(self, dataset_name: str, records: list[dict]) -> list[dict]:
        """
        Transform raw ERP records into the standard CFO data model.
        Base implementation returns records as-is; connectors should
        override for ERP-specific field mapping.
        """
        return records

    def __repr__(self) -> str:
        connected = "connected" if self._connected else "disconnected"
        return f"<{type(self).__name__} name={self.config.name!r} {connected}>"
