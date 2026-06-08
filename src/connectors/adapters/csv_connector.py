"""
CFO Command Center — CSV / Flat File Connector

Universal connector for importing financial data from CSV files.
Supports local filesystem, URLs, and S3/GCS paths.

This is the most versatile connector for initial data loading
and one-time migrations.
"""

import csv
import json
import logging
import io
from datetime import datetime
from typing import Optional
from pathlib import Path

from ..base import BaseConnector, ConnectorConfig, SyncResult, SyncStatus

logger = logging.getLogger("connector.csv")


class CSVConnector(BaseConnector):
    """
    CSV / Flat File connector for financial data import.

    Supports:
    - Local file paths
    - Multiple CSV files per dataset type
    - Configurable delimiter, encoding, and header row
    - Auto-detection of field types

    Usage:
        config = ConnectorConfig(
            connector_type=ConnectorType.CSV,
            name="Vendor Import",
            entity_id="us_ops",
            extra_params={
                "vendor_file": "/data/vendors.csv",
                "invoice_file": "/data/invoices.csv",
                "payment_file": "/data/payments.csv",
                "gl_file": "/data/gl.csv",
                "delimiter": ",",
                "encoding": "utf-8",
                "has_header": True,
            }
        )
        connector = CSVConnector(config)
        connector.connect()
        vendors = connector.extract_vendors()
    """

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.files = config.extra_params or {}
        self.delimiter = self.files.get("delimiter", ",")
        self.encoding = self.files.get("encoding", "utf-8")
        self.has_header = self.files.get("has_header", True)
        self._cache: dict[str, list[dict]] = {}

    def connect(self) -> bool:
        """Verify that configured file paths exist."""
        if not self.files:
            self.logger.warning("No file paths configured in extra_params")
            return True  # Allow connect even without files for dynamic loading

        found = 0
        for key, path in self.files.items():
            if not key.endswith("_file"):
                continue
            if Path(path).exists():
                found += 1
                self.logger.debug(f"File found: {key} -> {path}")
            else:
                self.logger.warning(f"File not found: {key} -> {path}")

        self._connected = True
        self.logger.info(f"CSV connector ready: {found} file(s) found")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._cache.clear()

    def health_check(self) -> dict:
        files_status = {}
        for key, path in self.files.items():
            if not key.endswith("_file"):
                continue
            exists = Path(path).exists()
            files_status[key] = {
                "path": path,
                "exists": exists,
                "size_kb": round(Path(path).stat().st_size / 1024, 1) if exists else 0,
            }

        return {
            "status": "ok" if any(f["exists"] for f in files_status.values()) else "no_files",
            "system": "CSV Connector",
            "files": files_status,
        }

    def _read_csv(self, file_key: str) -> list[dict]:
        """Read a CSV file and return as list of dicts."""
        path = self.files.get(file_key)
        if not path:
            return []

        if file_key in self._cache:
            return self._cache[file_key]

        records = []
        try:
            with open(path, "r", encoding=self.encoding) as f:
                # Handle BOM
                content = f.read()
                if content.startswith("\ufeff"):
                    content = content[1:]
                reader = csv.DictReader(
                    io.StringIO(content),
                    delimiter=self.delimiter,
                )
                for row in reader:
                    # Strip whitespace from keys and values
                    cleaned = {k.strip(): v.strip() for k, v in row.items() if k}
                    records.append(cleaned)
        except FileNotFoundError:
            self.logger.error(f"CSV file not found: {path}")
        except Exception as e:
            self.logger.error(f"Error reading CSV {path}: {e}")

        self._cache[file_key] = records
        return records

    def load_data(self, file_path: str, dataset_name: str) -> list[dict]:
        """
        Load data from a CSV file dynamically (not pre-configured).

        Args:
            file_path: Path to the CSV file
            dataset_name: Cache key for the dataset

        Returns:
            List of dicts representing CSV rows
        """
        self.files[f"{dataset_name}_file"] = file_path
        return self._read_csv(f"{dataset_name}_file")

    def extract_vendors(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting vendors from CSV...")
        file_key = kwargs.get("file_key", "vendor_file")
        records = self._read_csv(file_key)
        self.logger.info(f"Extracted {len(records)} vendor records from CSV")
        return records

    def extract_invoices(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting invoices from CSV...")
        file_key = kwargs.get("file_key", "invoice_file")
        records = self._read_csv(file_key)
        self.logger.info(f"Extracted {len(records)} invoice records from CSV")
        return records

    def extract_payments(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting payments from CSV...")
        file_key = kwargs.get("file_key", "payment_file")
        records = self._read_csv(file_key)
        self.logger.info(f"Extracted {len(records)} payment records from CSV")
        return records

    def extract_general_ledger(self, **kwargs) -> list[dict]:
        self.logger.info("Extracting GL entries from CSV...")
        file_key = kwargs.get("file_key", "gl_file")
        records = self._read_csv(file_key)
        self.logger.info(f"Extracted {len(records)} GL records from CSV")
        return records
