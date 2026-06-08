"""
CFO Command Center — Data Normalization Layer

Transforms raw ERP data from any connector into the standardized
CFO Command Center data model. Handles field mapping, type coercion,
currency conversion, and validation.

Supports per-connector field mappings and custom transformation rules.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Callable, Optional
from decimal import Decimal, InvalidOperation

logger = logging.getLogger("connector.normalizer")


# ── Standard Data Model (CFO Canonical Format) ──────────────────────

STANDARD_FIELDS = {
    "vendor": {
        "vendor_name": {"type": "string", "required": True},
        "vendor_id": {"type": "string"},
        "category": {"type": "string"},
        "payment_terms": {"type": "string"},
        "early_pay_discount": {"type": "string"},
        "annual_spend": {"type": "number"},
        "risk_rating": {"type": "string"},
        "on_time_delivery": {"type": "percent"},
        "quality_score": {"type": "string"},
        "strategic_priority": {"type": "string"},
        "status": {"type": "string"},
        "contract_end_date": {"type": "date"},
        "currency": {"type": "string"},
        "entity_code": {"type": "string"},
    },
    "invoice": {
        "invoice_number": {"type": "string", "required": True},
        "vendor_name": {"type": "string", "required": True},
        "invoice_date": {"type": "date"},
        "due_date": {"type": "date"},
        "original_amount": {"type": "number"},
        "outstanding_balance": {"type": "number"},
        "invoice_type": {"type": "string"},  # AP / AR
        "entity_name": {"type": "string"},
        "aging_bucket": {"type": "string"},
        "status": {"type": "string"},
        "currency": {"type": "string"},
        "entity_code": {"type": "string"},
    },
    "payment": {
        "payment_id": {"type": "string", "required": True},
        "vendor_name": {"type": "string", "required": True},
        "invoice_amount": {"type": "number"},
        "payment_date": {"type": "date"},
        "due_date": {"type": "date"},
        "early_pay_deadline": {"type": "date"},
        "discount_available": {"type": "string"},
        "payment_status": {"type": "string"},
        "currency": {"type": "string"},
        "entity_code": {"type": "string"},
    },
    "general_ledger": {
        "account_code": {"type": "string", "required": True},
        "account_name": {"type": "string"},
        "period": {"type": "string"},
        "debit": {"type": "number"},
        "credit": {"type": "number"},
        "balance": {"type": "number"},
        "account_type": {"type": "string"},  # Asset, Liability, Equity, Revenue, Expense
        "sub_type": {"type": "string"},
        "currency": {"type": "string"},
        "entity_code": {"type": "string"},
    },
}


@dataclass
class FieldMapping:
    """Maps a source field to a standard field with optional transformation."""
    source_field: str       # Field name in the source ERP
    target_field: str       # Standard field name in CFO model
    transform: Optional[Callable] = None  # Custom transformation function
    default_value: Any = None
    required: bool = False


@dataclass
class ValidationResult:
    """Result of validating a record against the standard model."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    record: dict = field(default_factory=dict)


class Normalizer:
    """
    Transforms raw ERP data into the standard CFO Command Center model.

    Usage:
        normalizer = Normalizer("sap")
        normalizer.set_mapping("vendor", [
            FieldMapping("LIFNR", "vendor_id"),
            FieldMapping("NAME1", "vendor_name"),
            FieldMapping("WAERS", "currency"),
            FieldMapping("BUKRS", "entity_code"),
        ])
        normalized = normalizer.normalize("vendor", raw_sap_data)
    """

    def __init__(self, connector_type: str, entity_code: str = ""):
        self.connector_type = connector_type.lower()
        self.entity_code = entity_code
        self._mappings: dict[str, list[FieldMapping]] = {}
        self._validators: dict[str, list[Callable]] = {}
        self.logger = logging.getLogger(f"normalizer.{connector_type}")

    # ── Mapping Registration ─────────────────────────────────────────

    def set_mapping(self, dataset: str, mappings: list[FieldMapping]) -> None:
        """Register field mappings for a dataset type."""
        self._mappings[dataset] = mappings
        self.logger.debug(f"Registered {len(mappings)} field mappings for '{dataset}'")

    def set_validator(self, dataset: str, validator: Callable) -> None:
        """Register a custom validation function for a dataset."""
        if dataset not in self._validators:
            self._validators[dataset] = []
        self._validators[dataset].append(validator)

    # ── Normalization ────────────────────────────────────────────────

    def normalize(self, dataset: str, records: list[dict]) -> tuple[list[dict], list[ValidationResult]]:
        """
        Normalize a list of raw records into the standard format.

        Args:
            dataset: Dataset type (vendor, invoice, payment, general_ledger)
            records: List of raw records from the ERP connector

        Returns:
            Tuple of (normalized_records, validation_results)
        """
        if dataset not in self._mappings:
            self.logger.warning(f"No mappings registered for '{dataset}', using passthrough")
            return records, []

        mappings = self._mappings[dataset]
        normalized = []
        validation_results = []

        for i, record in enumerate(records):
            norm_record, validation = self._normalize_record(dataset, record, mappings)
            normalized.append(norm_record)
            validation_results.append(validation)

            if not validation.is_valid:
                self.logger.warning(
                    f"Record {i+1} validation failed: {validation.errors}"
                )

        valid_count = sum(1 for v in validation_results if v.is_valid)
        self.logger.info(
            f"Normalized {len(records)} '{dataset}' records: "
            f"{valid_count} valid, {len(records) - valid_count} with issues"
        )
        return normalized, validation_results

    def _normalize_record(self, dataset: str, record: dict,
                          mappings: list[FieldMapping]) -> tuple[dict, ValidationResult]:
        """Normalize a single record using the registered mappings."""
        norm_record = {}
        errors = []
        warnings = []

        # Apply field mappings
        for mapping in mappings:
            value = record.get(mapping.source_field)

            # Check required fields
            if mapping.required and (value is None or value == ""):
                errors.append(f"Required field '{mapping.target_field}' (source: '{mapping.source_field}') is missing")

            # Apply custom transformation
            if mapping.transform and value is not None:
                try:
                    value = mapping.transform(value)
                except Exception as e:
                    warnings.append(f"Transform error on '{mapping.source_field}': {e}")
                    value = mapping.default_value

            # Apply default value
            if value is None and mapping.default_value is not None:
                value = mapping.default_value

            if value is not None:
                norm_record[mapping.target_field] = value

        # Inject entity code if configured
        if self.entity_code:
            norm_record["entity_code"] = self.entity_code

        # Type coercion based on standard model
        if dataset in STANDARD_FIELDS:
            norm_record = self._coerce_types(dataset, norm_record)

        # Run custom validators
        for validator in self._validators.get(dataset, []):
            try:
                validator(norm_record, errors, warnings)
            except Exception as e:
                warnings.append(f"Validator error: {e}")

        validation = ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            record=norm_record,
        )
        return norm_record, validation

    def _coerce_types(self, dataset: str, record: dict) -> dict:
        """Coerce field values to the correct types per the standard model."""
        field_defs = STANDARD_FIELDS.get(dataset, {})
        coerced = {}

        for key, value in record.items():
            if key not in field_defs:
                coerced[key] = value
                continue

            field_type = field_defs[key]["type"]

            if field_type == "number" and value is not None:
                coerced[key] = self._to_number(value)
            elif field_type == "percent" and value is not None:
                coerced[key] = self._to_percent(value)
            elif field_type == "date" and value is not None:
                coerced[key] = self._to_date(value)
            else:
                coerced[key] = value

        return coerced

    # ── Type Coercion Helpers ────────────────────────────────────────

    @staticmethod
    def _to_number(value: Any) -> Optional[float]:
        """Convert a value to a float, handling currency formats."""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace("$", "").replace(",", "").replace(" ", "").strip()
            if not cleaned or cleaned == "-":
                return None
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    @staticmethod
    def _to_percent(value: Any) -> Optional[float]:
        """Convert a value to a decimal percentage (0.0 - 1.0)."""
        num = Normalizer._to_number(value)
        if num is None:
            return None
        if num > 1:  # e.g., 97 -> 0.97
            return num / 100.0
        return num

    @staticmethod
    def _to_date(value: Any) -> Optional[str]:
        """Convert a value to an ISO date string (YYYY-MM-DD)."""
        if value is None:
            return None
        if isinstance(value, (date, datetime)):
            return value.strftime("%Y-%m-%d") if isinstance(value, date) else value.strftime("%Y-%m-%d")
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y",
                        "%m-%d-%Y", "%m/%d/%Y", "%Y%m%d", "%d.%m.%Y"):
                try:
                    return datetime.strptime(value.strip(), fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
            return value  # Return as-is if no format matches
        return None

    # ── Predefined Mappings ──────────────────────────────────────────

    @classmethod
    def get_sap_mappings(cls) -> dict[str, list[FieldMapping]]:
        """Return predefined field mappings for SAP S/4HANA."""
        return {
            "vendor": [
                FieldMapping("LIFNR", "vendor_id"),
                FieldMapping("NAME1", "vendor_name", required=True),
                FieldMapping("BUKRS", "entity_code"),
                FieldMapping("WAERS", "currency", default_value="USD"),
                FieldMapping("ZTERM", "payment_terms"),
                FieldMapping("KTOKK", "category"),
                FieldMapping("ERNAM", "notes"),
            ],
            "invoice": [
                FieldMapping("BELNR", "invoice_number", required=True),
                FieldMapping("LIFNR", "vendor_name"),
                FieldMapping("BUDAT", "invoice_date"),
                FieldMapping("ZFBDT", "due_date"),
                FieldMapping("WRBTR", "original_amount"),
                FieldMapping("DMBTR", "outstanding_balance"),
                FieldMapping("BUKRS", "entity_code"),
                FieldMapping("WAERS", "currency"),
                FieldMapping("SHKZG", "invoice_type",
                             transform=lambda v: "AP" if v == "S" else "AR"),
                FieldMapping("BLART", "status"),
            ],
            "payment": [
                FieldMapping("BELNR", "payment_id", required=True),
                FieldMapping("LIFNR", "vendor_name"),
                FieldMapping("WRBTR", "invoice_amount"),
                FieldMapping("BUDAT", "payment_date"),
                FieldMapping("ZFBDT", "due_date"),
                FieldMapping("BUKRS", "entity_code"),
                FieldMapping("WAERS", "currency"),
            ],
            "general_ledger": [
                FieldMapping("HKONT", "account_code", required=True),
                FieldMapping("TXT50", "account_name"),
                FieldMapping("BUDAT", "period"),
                FieldMapping("SHKZG", "debit",
                             transform=lambda v: None if v == "H" else v),
                FieldMapping("SHKZG", "credit",
                             transform=lambda v: None if v == "S" else v),
                FieldMapping("DMBTR", "balance"),
                FieldMapping("BUKRS", "entity_code"),
                FieldMapping("WAERS", "currency"),
                FieldMapping("KTOKS", "account_type"),
            ],
        }

    @classmethod
    def get_quickbooks_mappings(cls) -> dict[str, list[FieldMapping]]:
        """Return predefined field mappings for QuickBooks Online."""
        return {
            "vendor": [
                FieldMapping("Id", "vendor_id"),
                FieldMapping("DisplayName", "vendor_name", required=True),
                FieldMapping("CompanyName", "category"),
                FieldMapping("Balance", "annual_spend"),
                FieldMapping("PrimaryEmail_Address", "notes"),
                FieldMapping("CurrencyRef_value", "currency", default_value="USD"),
            ],
            "invoice": [
                FieldMapping("Id", "invoice_number", required=True),
                FieldMapping("VendorRef_name", "vendor_name", required=True),
                FieldMapping("TxnDate", "invoice_date"),
                FieldMapping("DueDate", "due_date"),
                FieldMapping("TotalAmt", "original_amount"),
                FieldMapping("Balance", "outstanding_balance"),
                FieldMapping("CurrencyRef_value", "currency"),
                FieldMapping("TxnStatus", "status"),
            ],
            "payment": [
                FieldMapping("Id", "payment_id", required=True),
                FieldMapping("VendorRef_name", "vendor_name"),
                FieldMapping("TotalAmt", "invoice_amount"),
                FieldMapping("TxnDate", "payment_date"),
                FieldMapping("CurrencyRef_value", "currency"),
                FieldMapping("TxnStatus", "payment_status"),
            ],
            "general_ledger": [
                FieldMapping("Id", "account_code", required=True),
                FieldMapping("Name", "account_name"),
                FieldMapping("TxnDate", "period"),
                FieldMapping("Amount", "balance"),
                FieldMapping("CurrencyRef_value", "currency"),
                FieldMapping("AccountType", "account_type"),
                FieldMapping("AccountSubType", "sub_type"),
            ],
        }

    @classmethod
    def get_netsuite_mappings(cls) -> dict[str, list[FieldMapping]]:
        """Return predefined field mappings for NetSuite."""
        return {
            "vendor": [
                FieldMapping("internalid", "vendor_id"),
                FieldMapping("companyname", "vendor_name", required=True),
                FieldMapping("subsidiary", "entity_code"),
                FieldMapping("currency", "currency"),
                FieldMapping("terms", "payment_terms"),
                FieldMapping("category", "category"),
                FieldMapping("email", "notes"),
            ],
            "invoice": [
                FieldMapping("tranid", "invoice_number", required=True),
                FieldMapping("entity_display", "vendor_name", required=True),
                FieldMapping("trandate", "invoice_date"),
                FieldMapping("duedate", "due_date"),
                FieldMapping("total", "original_amount"),
                FieldMapping("amountremaining", "outstanding_balance"),
                FieldMapping("subsidiary", "entity_code"),
                FieldMapping("currency", "currency"),
                FieldMapping("status", "status"),
            ],
            "payment": [
                FieldMapping("internalid", "payment_id", required=True),
                FieldMapping("entity_display", "vendor_name"),
                FieldMapping("payment", "invoice_amount"),
                FieldMapping("trandate", "payment_date"),
                FieldMapping("subsidiary", "entity_code"),
                FieldMapping("currency", "currency"),
                FieldMapping("status", "payment_status"),
            ],
            "general_ledger": [
                FieldMapping("account_number", "account_code", required=True),
                FieldMapping("account_name", "account_name"),
                FieldMapping("postingperiod", "period"),
                FieldMapping("debit", "debit"),
                FieldMapping("credit", "credit"),
                FieldMapping("amount", "balance"),
                FieldMapping("subsidiary", "entity_code"),
                FieldMapping("currency", "currency"),
                FieldMapping("type_display", "account_type"),
            ],
        }
