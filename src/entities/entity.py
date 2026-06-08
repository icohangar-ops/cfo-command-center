"""
CFO Command Center — Entity and Entity Registry

Defines the Entity dataclass and EntityRegistry for managing
multiple legal entities in the CFO Command Center.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..connectors.base import ConnectorConfig, ConnectorType

logger = logging.getLogger("entity.registry")


@dataclass
class Entity:
    """
    Represents a legal entity or business unit.

    Each entity maps to:
    - One or more ERP connectors for data ingestion
    - A set of Notion databases for financial tracking
    - A currency for consolidation
    """
    entity_id: str
    name: str
    legal_name: str = ""
    country: str = ""
    currency: str = "USD"
    reporting_currency: str = "USD"
    enabled: bool = True
    description: str = ""
    connectors: list = field(default_factory=list)
    database_map: dict = field(default_factory=dict)
    exchange_rate: float = 1.0
    parent_entity_id: Optional[str] = None
    tags: list = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "legal_name": self.legal_name,
            "country": self.country,
            "currency": self.currency,
            "reporting_currency": self.reporting_currency,
            "enabled": self.enabled,
            "description": self.description,
            "connectors": [
                c if isinstance(c, dict) else {
                    "connector_type": c.connector_type.value if hasattr(c.connector_type, "value") else str(c.connector_type),
                    "name": c.name,
                    "entity_id": c.entity_id,
                    "base_url": c.base_url,
                    "api_key": c.api_key,
                    "username": c.username,
                    "password": c.password,
                    "token": c.token,
                    "realm": c.realm,
                    "company_id": c.company_id,
                    "enabled": c.enabled,
                    "sync_frequency": c.sync_frequency,
                    "batch_size": c.batch_size,
                    "timeout_seconds": c.timeout_seconds,
                    "retry_attempts": c.retry_attempts,
                    "retry_delay_seconds": c.retry_delay_seconds,
                    "extra_params": c.extra_params,
                }
                for c in self.connectors
            ],
            "database_map": self.database_map,
            "exchange_rate": self.exchange_rate,
            "parent_entity_id": self.parent_entity_id,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Entity":
        connectors = data.get("connectors", [])
        if connectors and isinstance(connectors[0], dict):
            parsed = []
            for c in connectors:
                ct = c.get("connector_type", "csv")
                try:
                    connector_type = ConnectorType(ct)
                except ValueError:
                    connector_type = ConnectorType.CSV
                parsed.append(ConnectorConfig(
                    connector_type=connector_type,
                    name=c.get("name", "unnamed"),
                    entity_id=data.get("entity_id", ""),
                    base_url=c.get("base_url"),
                    api_key=c.get("api_key"),
                    username=c.get("username"),
                    password=c.get("password"),
                    token=c.get("token"),
                    realm=c.get("realm"),
                    company_id=c.get("company_id"),
                    enabled=c.get("enabled", True),
                    sync_frequency=c.get("sync_frequency", "daily"),
                    batch_size=c.get("batch_size", 100),
                    timeout_seconds=c.get("timeout_seconds", 60),
                    retry_attempts=c.get("retry_attempts", 3),
                    retry_delay_seconds=c.get("retry_delay_seconds", 5),
                    extra_params=c.get("extra_params", {}),
                ))
            data["connectors"] = parsed
        return cls(**data)


class EntityRegistry:
    """
    Central registry for all entities in the CFO Command Center.

    Provides CRUD operations, entity lookup, and hierarchical
    entity management for multi-entity groups.
    """

    def __init__(self):
        self._entities: dict[str, Entity] = {}

    def register(self, entity: Entity) -> Entity:
        """Register a new entity or update an existing one."""
        entity.updated_at = datetime.now(timezone.utc).isoformat()
        self._entities[entity.entity_id] = entity
        logger.info(f"Registered entity: {entity.name} ({entity.entity_id})")
        return entity

    def unregister(self, entity_id: str) -> bool:
        """Remove an entity from the registry."""
        if entity_id in self._entities:
            del self._entities[entity_id]
            logger.info(f"Unregistered entity: {entity_id}")
            return True
        return False

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get an entity by its ID."""
        return self._entities.get(entity_id)

    def list_entities(self, enabled_only: bool = True) -> list[Entity]:
        """List all registered entities."""
        entities = list(self._entities.values())
        if enabled_only:
            entities = [e for e in entities if e.enabled]
        return entities

    def get_entities_by_country(self, country: str) -> list[Entity]:
        """Get all entities in a specific country."""
        return [e for e in self._entities.values()
                if e.country.upper() == country.upper() and e.enabled]

    def get_entities_by_currency(self, currency: str) -> list[Entity]:
        """Get all entities using a specific currency."""
        return [e for e in self._entities.values()
                if e.currency.upper() == currency.upper() and e.enabled]

    def get_child_entities(self, parent_id: str) -> list[Entity]:
        """Get all child entities of a parent entity."""
        return [e for e in self._entities.values()
                if e.parent_entity_id == parent_id and e.enabled]

    def get_root_entities(self) -> list[Entity]:
        """Get all root entities (no parent)."""
        return [e for e in self._entities.values()
                if e.parent_entity_id is None and e.enabled]

    def get_entity_tree(self, parent_id: Optional[str] = None) -> list[dict]:
        """Get a hierarchical tree of entities."""
        if parent_id:
            children = self.get_child_entities(parent_id)
        else:
            children = self.get_root_entities()

        tree = []
        for entity in children:
            node = {
                "entity_id": entity.entity_id,
                "name": entity.name,
                "currency": entity.currency,
                "country": entity.country,
                "enabled": entity.enabled,
                "connector_count": len(entity.connectors),
            }
            child_tree = self.get_entity_tree(entity.entity_id)
            if child_tree:
                node["children"] = child_tree
            tree.append(node)
        return tree

    def set_exchange_rate(self, entity_id: str, rate: float) -> bool:
        """Update the exchange rate for an entity."""
        entity = self.get_entity(entity_id)
        if entity:
            entity.exchange_rate = rate
            entity.updated_at = datetime.now(timezone.utc).isoformat()
            logger.info(f"Updated exchange rate for {entity_id}: {rate}")
            return True
        return False

    def convert_to_group_currency(self, entity_id: str, amount: float) -> float:
        """Convert an amount from entity currency to group reporting currency."""
        entity = self.get_entity(entity_id)
        if entity:
            return amount * entity.exchange_rate
        return amount

    def add_connector(self, entity_id: str, connector_config) -> bool:
        """Add a connector configuration to an entity."""
        entity = self.get_entity(entity_id)
        if entity:
            entity.connectors.append(connector_config)
            entity.updated_at = datetime.now(timezone.utc).isoformat()
            logger.info(f"Added connector '{connector_config.name}' to entity '{entity_id}'")
            return True
        return False

    def get_connectors(self, entity_id: str) -> list:
        """Get all connectors for an entity."""
        entity = self.get_entity(entity_id)
        return entity.connectors if entity else []

    def set_database_map(self, entity_id: str, db_map: dict) -> bool:
        """Set the Notion database IDs for an entity."""
        entity = self.get_entity(entity_id)
        if entity:
            entity.database_map = db_map
            entity.updated_at = datetime.now(timezone.utc).isoformat()
            return True
        return False

    def get_database_map(self, entity_id: str) -> dict:
        """Get the Notion database IDs for an entity."""
        entity = self.get_entity(entity_id)
        return entity.database_map if entity else {}

    def get_summary(self) -> dict:
        """Get a summary of all registered entities."""
        entities = self.list_entities(enabled_only=False)
        active = [e for e in entities if e.enabled]
        countries = set(e.country for e in active if e.country)
        currencies = set(e.currency for e in active)
        total_connectors = sum(len(e.connectors) for e in active)

        return {
            "total_entities": len(entities),
            "active_entities": len(active),
            "countries": sorted(countries),
            "currencies": sorted(currencies),
            "total_connectors": total_connectors,
            "entities": [
                {
                    "entity_id": e.entity_id,
                    "name": e.name,
                    "country": e.country,
                    "currency": e.currency,
                    "enabled": e.enabled,
                    "connector_count": len(e.connectors),
                }
                for e in entities
            ],
        }

    def to_json(self) -> str:
        """Serialize the entire registry to JSON."""
        data = {
            "entities": [e.to_dict() for e in self._entities.values()],
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        return json.dumps(data, indent=2)

    def from_json(self, json_str: str) -> None:
        """Load the registry from a JSON string."""
        data = json.loads(json_str)
        self._entities.clear()
        for entity_data in data.get("entities", []):
            entity = Entity.from_dict(entity_data)
            self._entities[entity.entity_id] = entity
        logger.info(f"Loaded {len(self._entities)} entities from JSON")

    def save_to_file(self, file_path: str) -> None:
        """Save registry to a JSON file."""
        with open(file_path, "w") as f:
            f.write(self.to_json())
        logger.info(f"Saved registry to {file_path}")

    def load_from_file(self, file_path: str) -> None:
        """Load registry from a JSON file."""
        with open(file_path, "r") as f:
            self.from_json(f.read())
