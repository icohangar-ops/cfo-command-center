"""
CFO Command Center — Notion API Client
Bidirectional read/write wrapper for all finance databases.
"""

import os
import json
import logging
from typing import Any, Optional
from datetime import datetime, date
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("notion_client")


class NotionClient:
    """Low-level Notion REST API wrapper with retry logic."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("NOTION_TOKEN")
        self.version = os.getenv("NOTION_VERSION", "2022-06-28")
        self.base = "https://api.notion.com/v1"
        if not self.token:
            raise ValueError("NOTION_TOKEN not set. Pass token or set env var.")
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.version,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body else None
        req = Request(url, data=data, headers=self._headers, method=method)
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            error_body = e.read().decode()
            logger.error(f"HTTP {e.code} on {method} {path}: {error_body}")
            raise
        except URLError as e:
            logger.error(f"URL error on {method} {path}: {e.reason}")
            raise

    # ── Query ───────────────────────────────────────────────────────────
    def query_database(self, database_id: str, filter_obj: Optional[dict] = None,
                       sorts: Optional[list] = None, page_size: int = 100) -> list[dict]:
        """Query a Notion database, auto-paginating through all results."""
        body: dict[str, Any] = {"page_size": page_size}
        if filter_obj:
            body["filter"] = filter_obj
        if sorts:
            body["sorts"] = sorts

        results = []
        while True:
            resp = self._request("POST", f"/databases/{database_id}/query", body)
            results.extend(resp.get("results", []))
            cursor = resp.get("next_cursor")
            if not resp.get("has_more") or not cursor:
                break
            body["start_cursor"] = cursor
        return results

    # ── Create Page ─────────────────────────────────────────────────────
    def create_page(self, database_id: str, properties: dict,
                    children: Optional[list] = None) -> dict:
        body: dict[str, Any] = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        if children:
            body["children"] = children
        return self._request("POST", "/pages", body)

    # ── Update Page ─────────────────────────────────────────────────────
    def update_page(self, page_id: str, properties: dict,
                    archived: bool = False) -> dict:
        return self._request("PATCH", f"/pages/{page_id}", {
            "properties": properties,
            "archived": archived,
        })

    # ── Append Blocks ───────────────────────────────────────────────────
    def append_blocks(self, page_id: str, children: list[dict]) -> dict:
        return self._request("PATCH", f"/blocks/{page_id}/children", {
            "children": children,
        })

    # ── Get Page ────────────────────────────────────────────────────────
    def get_page(self, page_id: str) -> dict:
        return self._request("GET", f"/pages/{page_id}")

    # ── Get Database Schema ─────────────────────────────────────────────
    def get_database(self, database_id: str) -> dict:
        return self._request("GET", f"/databases/{database_id}")


# ── Helper: Extract typed property values ──────────────────────────────

def get_title(props: dict, key: str) -> str:
    """Extract title text from a Notion page property."""
    items = props.get(key, {}).get("title", [])
    return items[0]["plain_text"] if items else ""


def get_rich_text(props: dict, key: str) -> str:
    items = props.get(key, {}).get("rich_text", [])
    return items[0]["plain_text"] if items else ""


def get_select(props: dict, key: str) -> Optional[str]:
    sel = props.get(key, {}).get("select")
    return sel["name"] if sel else None


def get_number(props: dict, key: str) -> Optional[float]:
    return props.get(key, {}).get("number")


def get_date(props: dict, key: str) -> Optional[str]:
    d = props.get(key, {}).get("date")
    return d.get("start") if d else None


def get_formula_number(props: dict, key: str) -> Optional[float]:
    """Extract number from a formula property."""
    f = props.get(key, {}).get("formula", {})
    if f.get("type") == "number":
        return f.get("number")
    return None


def to_rich_text(text: str) -> list[dict]:
    """Wrap a string as a Notion rich_text value."""
    return [{"type": "text", "text": {"content": text}}]


def today_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")
