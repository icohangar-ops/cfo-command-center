"""
CFO Command Center — P4 Demo Script

Demonstrates multi-entity ERP integration with sample data.
Creates entities, configures connectors, runs sync pipeline,
and generates a consolidated report.

Usage:
    cd /path/to/cfo-command-center
    python -m src.demo_p4
"""

import json
import logging
import os
import sys

# Ensure the parent directory is in the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.connectors.base import ConnectorConfig, ConnectorType
from src.entities.entity import Entity, EntityRegistry
from src.entities.manager import MultiEntityManager
from src.notion_client import NotionClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("demo_p4")


def create_sample_entities() -> EntityRegistry:
    """Create sample multi-entity configuration."""
    registry = EntityRegistry()

    # Entity 1: US Operations
    us_ops = Entity(
        entity_id="us_ops",
        name="US Operations LLC",
        legal_name="CFO Corp US Operations LLC",
        country="US",
        currency="USD",
        description="Headquarters entity with primary operations",
        tags=["primary", "headquarters"],
    )
    us_ops.database_map = {
        "working_capital": os.getenv("DB_WORKING_CAPITAL", ""),
        "cash_flow_forecast": os.getenv("DB_CASH_FLOW_FORECAST", ""),
        "vendor_scorecard": os.getenv("DB_VENDOR_SCORECARD", ""),
        "payment_optimization": os.getenv("DB_PAYMENT_OPTIMIZATION", ""),
        "ap_ar_aging": os.getenv("DB_AP_AR_AGING", ""),
    }
    registry.register(us_ops)

    # Entity 2: EU GmbH
    eu_gmbh = Entity(
        entity_id="eu_gmbh",
        name="EU GmbH",
        legal_name="CFO Corp Deutschland GmbH",
        country="DE",
        currency="EUR",
        exchange_rate=1.08,  # EUR to USD
        description="European subsidiary headquartered in Frankfurt",
        tags=["subsidiary", "eu"],
    )
    registry.register(eu_gmbh)

    # Entity 3: APAC Pte Ltd
    apac = Entity(
        entity_id="apac_sg",
        name="APAC Pte Ltd",
        legal_name="CFO Corp Asia Pacific Pte Ltd",
        country="SG",
        currency="SGD",
        exchange_rate=0.74,  # SGD to USD
        description="Asia-Pacific operations hub",
        tags=["subsidiary", "apac"],
    )
    registry.register(apac)

    # Entity 4: Canada Inc
    ca = Entity(
        entity_id="ca_ops",
        name="Canada Inc",
        legal_name="CFO Corp Canada Inc",
        country="CA",
        currency="CAD",
        exchange_rate=0.73,  # CAD to USD
        description="Canadian operations entity",
        tags=["subsidiary", "north_america"],
    )
    registry.register(ca)

    return registry


def create_sample_connectors(registry: EntityRegistry) -> None:
    """Configure sample ERP connectors for each entity."""
    # US Ops — SAP S/4HANA
    us_connector = ConnectorConfig(
        connector_type=ConnectorType.SAP,
        name="US SAP S/4HANA",
        entity_id="us_ops",
        base_url="https://us-sap.example.com",
        username="CFO_API_USER",
        password="***",
        company_id="1000",
        sync_frequency="hourly",
        batch_size=200,
        enabled=False,  # Demo mode — don't actually connect
    )
    registry.add_connector("us_ops", us_connector)

    # US Ops — QuickBooks backup
    us_qb = ConnectorConfig(
        connector_type=ConnectorType.QUICKBOOKS,
        name="US QuickBooks Online",
        entity_id="us_ops",
        realm="123456789",
        token="***",
        sync_frequency="daily",
        enabled=False,
    )
    registry.add_connector("us_ops", us_qb)

    # EU GmbH — Oracle Cloud ERP
    eu_connector = ConnectorConfig(
        connector_type=ConnectorType.ORACLE,
        name="EU Oracle Cloud ERP",
        entity_id="eu_gmbh",
        base_url="https://eu-oracle.example.com",
        token="***",
        company_id="DE01",
        sync_frequency="daily",
        batch_size=100,
        enabled=False,
    )
    registry.add_connector("eu_gmbh", eu_connector)

    # APAC — NetSuite
    apac_connector = ConnectorConfig(
        connector_type=ConnectorType.NETSUITE,
        name="APAC NetSuite",
        entity_id="apac_sg",
        realm="ABCORP",
        api_key="***",
        username="api@corp.com",
        password="***",
        company_id="SG01",
        sync_frequency="daily",
        enabled=False,
    )
    registry.add_connector("apac_sg", apac_connector)

    # Canada — CSV import (one-time migration)
    ca_connector = ConnectorConfig(
        connector_type=ConnectorType.CSV,
        name="Canada Data Import",
        entity_id="ca_ops",
        extra_params={
            "vendor_file": "/data/ca/vendors.csv",
            "invoice_file": "/data/ca/invoices.csv",
            "payment_file": "/data/ca/payments.csv",
            "gl_file": "/data/ca/gl.csv",
        },
        sync_frequency="manual",
        enabled=False,
    )
    registry.add_connector("ca_ops", ca_connector)


def demo_entity_registry(registry: EntityRegistry) -> None:
    """Demonstrate entity registry features."""
    print("\n" + "=" * 60)
    print("  ENTITY REGISTRY DEMO")
    print("=" * 60)

    # List all entities
    entities = registry.list_entities()
    print(f"\nRegistered entities: {len(entities)}")
    for e in entities:
        print(f"  - {e.name} ({e.entity_id}): {e.country}, {e.currency}")

    # Entity tree
    tree = registry.get_entity_tree()
    print(f"\nEntity tree: {json.dumps(tree, indent=2)}")

    # Currency conversion
    print("\nCurrency conversion examples:")
    for e in entities:
        sample = 1000000
        converted = registry.convert_to_group_currency(e.entity_id, sample)
        print(f"  {sample:,.0f} {e.currency} -> {converted:,.0f} USD (rate: {e.exchange_rate})")

    # Summary
    summary = registry.get_summary()
    print(f"\nRegistry summary: {json.dumps(summary, indent=2)}")

    # Connectors
    print("\nConnectors per entity:")
    for e in entities:
        connectors = registry.get_connectors(e.entity_id)
        print(f"  {e.name}: {len(connectors)} connector(s)")
        for c in connectors:
            print(f"    - {c.name} ({c.connector_type.value})")


def demo_connector_framework() -> None:
    """Demonstrate the connector framework with sample CSV data."""
    print("\n" + "=" * 60)
    print("  CONNECTOR FRAMEWORK DEMO")
    print("=" * 60)

    # Create sample CSV data
    import tempfile
    import csv as csv_mod

    tmp_dir = tempfile.mkdtemp()

    # Sample vendors CSV
    vendors_path = os.path.join(tmp_dir, "vendors.csv")
    with open(vendors_path, "w", newline="") as f:
        writer = csv_mod.DictWriter(f, ["vendor_name", "category", "annual_spend",
                                         "risk_rating", "on_time_delivery", "quality_score"])
        writer.writeheader()
        writer.writerow({"vendor_name": "Global Steel Corp", "category": "Raw Materials",
                         "annual_spend": 2400000, "risk_rating": "Low",
                         "on_time_delivery": 96, "quality_score": "A (95-100)"})
        writer.writerow({"vendor_name": "Pacific Logistics", "category": "Logistics",
                         "annual_spend": 890000, "risk_rating": "Medium",
                         "on_time_delivery": 91, "quality_score": "B (85-94)"})
        writer.writerow({"vendor_name": "TechParts GmbH", "category": "Components",
                         "annual_spend": 1500000, "risk_rating": "Low",
                         "on_time_delivery": 98, "quality_score": "A (95-100)"})

    # Create CSV connector
    config = ConnectorConfig(
        connector_type=ConnectorType.CSV,
        name="Sample CSV Import",
        entity_id="us_ops",
        extra_params={
            "vendor_file": vendors_path,
            "delimiter": ",",
            "encoding": "utf-8",
            "has_header": True,
        },
    )

    from src.connectors.adapters.csv_connector import CSVConnector
    from src.connectors.normalizer import Normalizer, FieldMapping

    connector = CSVConnector(config)
    connector.connect()

    # Health check
    health = connector.health_check()
    print(f"\nCSV Connector health: {json.dumps(health, indent=2)}")

    # Extract data
    vendors = connector.extract_vendors()
    print(f"\nExtracted {len(vendors)} vendors from CSV:")
    for v in vendors:
        spend = v.get('annual_spend', 0)
        try:
            spend_str = f"${float(spend):,.0f}"
        except (ValueError, TypeError):
            spend_str = str(spend)
        print(f"  - {v.get('vendor_name')}: {spend_str}")

    # Normalize
    normalizer = Normalizer("csv", entity_code="us_ops")
    normalizer.set_mapping("vendor", [
        FieldMapping("vendor_name", "vendor_name", required=True),
        FieldMapping("category", "category"),
        FieldMapping("annual_spend", "annual_spend"),
        FieldMapping("risk_rating", "risk_rating"),
        FieldMapping("on_time_delivery", "on_time_delivery"),
        FieldMapping("quality_score", "quality_score"),
    ])

    normalized, validations = normalizer.normalize("vendor", vendors)
    print(f"\nNormalized {len(normalized)} vendors:")
    for rec in normalized:
        spend = rec.get('annual_spend') or 0
        otd = rec.get('on_time_delivery') or 0
        try:
            spend_f = float(spend)
            otd_f = float(otd)
        except (ValueError, TypeError):
            spend_f = 0
            otd_f = 0
        print(f"  - {rec.get('vendor_name')}: ${spend_f:,.0f}, "
              f"OTD: {otd_f:.0%}, entity: {rec.get('entity_code')}")

    # Validation
    valid = sum(1 for v in validations if v.is_valid)
    print(f"\nValidation: {valid}/{len(validations)} records valid")
    for v in validations:
        if v.warnings:
            print(f"  Warnings: {v.warnings}")

    # Cleanup
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


def demo_normalizer_presets() -> None:
    """Demonstrate predefined normalizer mappings."""
    print("\n" + "=" * 60)
    print("  NORMALIZER PRESETS DEMO")
    print("=" * 60)

    from src.connectors.normalizer import Normalizer

    # SAP presets
    print("\nSAP S/4HANA field mappings:")
    sap_mappings = Normalizer.get_sap_mappings()
    for dataset, mappings in sap_mappings.items():
        print(f"\n  {dataset.upper()}:")
        for m in mappings:
            print(f"    {m.source_field:<12s} -> {m.target_field}")

    # QuickBooks presets
    print("\n\nQuickBooks Online field mappings:")
    qb_mappings = Normalizer.get_quickbooks_mappings()
    for dataset, mappings in qb_mappings.items():
        print(f"\n  {dataset.upper()}:")
        for m in mappings[:4]:
            print(f"    {m.source_field:<25s} -> {m.target_field}")
        if len(mappings) > 4:
            print(f"    ... and {len(mappings) - 4} more")

    # Supported connectors
    from src.connectors.adapters import list_supported_connectors
    print("\n\nSupported connectors:")
    for c in list_supported_connectors():
        print(f"  - {c['name']} ({c['type']}): {c['description'][:60]}...")


def main():
    """Run the full P4 demo."""
    print("=" * 60)
    print("  CFO COMMAND CENTER — P4 MULTI-ENTITY ERP INTEGRATION")
    print("  Demo Script")
    print("=" * 60)

    # 1. Entity Registry
    registry = create_sample_entities()
    create_sample_connectors(registry)
    demo_entity_registry(registry)

    # 2. Connector Framework
    demo_connector_framework()

    # 3. Normalizer Presets
    demo_normalizer_presets()

    # 4. Save registry
    registry_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "entity_registry.json")
    registry.save_to_file(registry_path)
    print(f"\nEntity registry saved to: {registry_path}")

    print("\n" + "=" * 60)
    print("  P4 DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
