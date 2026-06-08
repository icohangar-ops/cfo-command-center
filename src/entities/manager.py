"""
CFO Command Center — Multi-Entity Manager

High-level manager that coordinates multi-entity operations:
  - Sync all entities via their configured connectors
  - Run agents across all entities
  - Generate consolidated reports
  - Manage entity-level Notion databases
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from .entity import Entity, EntityRegistry
from ..notion_client import NotionClient, to_rich_text
from ..config import NOTION_TOKEN, PAGE_CFO_CENTER

logger = logging.getLogger("entity.manager")


class MultiEntityManager:
    """
    Coordinates multi-entity operations for the CFO Command Center.

    This is the primary interface for working with multiple entities:
    - Register and manage entities
    - Sync data from ERP connectors
    - Run AI agents per entity
    - Generate consolidated cross-entity reports

    Usage:
        manager = MultiEntityManager(notion_client)
        manager.registry.register(Entity(
            entity_id="us_ops",
            name="US Operations",
            currency="USD",
        ))
        result = manager.sync_all_entities()
        report = manager.generate_consolidated_report()
    """

    def __init__(self, notion_client: NotionClient = None):
        self.notion = notion_client or NotionClient(token=NOTION_TOKEN)
        self.registry = EntityRegistry()

    # ── Entity Management ────────────────────────────────────────────

    def register_entity(self, entity: Entity) -> Entity:
        """Register a new entity and optionally create its Notion databases."""
        registered = self.registry.register(entity)

        # Log to CFO page
        if self.notion:
            try:
                blocks = [
                    {"object": "block", "type": "callout",
                     "callout": {
                         "icon": {"emoji": "🏢"},
                         "rich_text": to_rich_text(
                             f"Entity registered: {entity.name} ({entity.entity_id}) — "
                             f"{entity.country}, {entity.currency}"
                         ),
                     }},
                ]
                self.notion.append_blocks(PAGE_CFO_CENTER, blocks)
            except Exception as e:
                logger.warning(f"Could not log entity registration to Notion: {e}")

        return registered

    def list_entities(self) -> list[dict]:
        """List all registered entities."""
        return [
            {
                "entity_id": e.entity_id,
                "name": e.name,
                "country": e.country,
                "currency": e.currency,
                "exchange_rate": e.exchange_rate,
                "connectors": len(e.connectors),
                "enabled": e.enabled,
            }
            for e in self.registry.list_entities()
        ]

    # ── Multi-Entity Sync ────────────────────────────────────────────

    def sync_entity(self, entity_id: str) -> dict:
        """Sync a single entity using its configured connectors."""
        entity = self.registry.get_entity(entity_id)
        if not entity:
            return {"error": f"Entity '{entity_id}' not found"}

        from ..connectors.pipeline import SyncPipeline
        pipeline = SyncPipeline(self.notion, entity_registry=self.registry)
        return pipeline.sync_entity(entity_id)

    def sync_all_entities(self) -> dict:
        """Sync all enabled entities."""
        from ..connectors.pipeline import SyncPipeline

        logger.info("Starting multi-entity sync...")
        pipeline = SyncPipeline(self.notion, entity_registry=self.registry)
        result = pipeline.sync_all_entities()

        # Log to Notion
        if self.notion:
            try:
                self._log_sync_result(result)
            except Exception as e:
                logger.warning(f"Could not log sync result to Notion: {e}")

        return result.to_dict()

    def _log_sync_result(self, result) -> None:
        """Write sync pipeline result to the CFO Command Center page."""
        blocks = [
            {"object": "block", "type": "divider", "divider": {}},
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": to_rich_text("Multi-Entity Sync Report")}},
            {"object": "block", "type": "callout",
             "callout": {
                 "icon": {"emoji": "🔄"},
                 "rich_text": to_rich_text(
                     f"Pipeline {result.pipeline_id}: {result.entities_synced} entities, "
                     f"{result.total_records} records, {result.total_errors} errors "
                     f"in {result.duration_seconds:.1f}s"
                 ),
             }},
        ]

        for er in result.entity_results:
            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": to_rich_text(
                        f"{er.get('entity_name', er.get('entity_id', 'Unknown'))}: "
                        f"{er.get('total_records', 0)} records, "
                        f"{er.get('total_errors', 0)} errors"
                    )
                },
            })

        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"Sync completed: {result.completed_at}"},
                    "annotations": {"italic": True, "strikethrough": False,
                                    "underline": False, "code": False,
                                    "bold": False, "color": "gray"}
                }]
            }
        })

        self.notion.append_blocks(PAGE_CFO_CENTER, blocks)

    # ── Cross-Entity Reporting ───────────────────────────────────────

    def generate_consolidated_report(self) -> dict:
        """Generate a consolidated financial snapshot across all entities."""
        from ..consolidation.agent import ConsolidationAgent

        agent = ConsolidationAgent(self.notion, self.registry)
        report = agent.run()
        return report

    # ── Persistence ──────────────────────────────────────────────────

    def save_registry(self, file_path: str) -> None:
        """Save entity registry to a JSON file."""
        self.registry.save_to_file(file_path)

    def load_registry(self, file_path: str) -> None:
        """Load entity registry from a JSON file."""
        self.registry.load_from_file(file_path)
