"""
CFO Command Center — Notion API Client
Bidirectional read/write wrapper for all finance databases.
"""

import os
import json
import time
import logging
from typing import Any, Optional
from datetime import datetime, date
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from cubiczan_resilience import FileIdempotencyStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("notion_client")

# Single-host, file-backed store shared across webhook + batch processes so a
# given (page, dedup-key) write-back executes at most once. Path is overridable
# via env for deployments with a writable shared volume.
_WRITEBACK_STORE_PATH = os.getenv(
    "NOTION_WRITEBACK_STATE", os.path.join(os.path.expanduser("~"), ".cfo_notion_writebacks.json")
)
_writeback_store = FileIdempotencyStore(_WRITEBACK_STORE_PATH)


class NotionClient:
    """Low-level Notion REST API wrapper.

    Retries 429 (rate limit) and 5xx (transient server) responses with
    exponential backoff, respecting a ``Retry-After`` header when present.
    """

    # Status codes worth retrying: rate limit + transient server errors.
    _RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, token: Optional[str] = None,
                 retry_attempts: int = 3, retry_delay_seconds: float = 5.0):
        self.token = token or os.getenv("NOTION_TOKEN")
        self.version = os.getenv("NOTION_VERSION", "2022-06-28")
        self.base = "https://api.notion.com/v1"
        # retry_attempts is the number of *additional* tries after the first.
        self.retry_attempts = max(0, int(retry_attempts))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))
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

        last_exc: Optional[Exception] = None
        for attempt in range(self.retry_attempts + 1):
            req = Request(url, data=data, headers=self._headers, method=method)
            try:
                with urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except HTTPError as e:
                last_exc = e
                error_body = e.read().decode()
                logger.error(f"HTTP {e.code} on {method} {path}: {error_body}")
                if e.code in self._RETRYABLE_STATUS and attempt < self.retry_attempts:
                    delay = self._retry_delay(attempt, getattr(e, "headers", None))
                    logger.warning(
                        f"Retrying {method} {path} in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{self.retry_attempts})"
                    )
                    time.sleep(delay)
                    continue
                raise
            except URLError as e:
                last_exc = e
                logger.error(f"URL error on {method} {path}: {e.reason}")
                if attempt < self.retry_attempts:
                    delay = self._retry_delay(attempt, None)
                    logger.warning(
                        f"Retrying {method} {path} in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{self.retry_attempts})"
                    )
                    time.sleep(delay)
                    continue
                raise
        # Should be unreachable: loop either returns or raises.
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Request failed without exception: {method} {path}")

    def _retry_delay(self, attempt: int, headers) -> float:
        """Compute backoff delay, honoring a Retry-After header when present."""
        if headers is not None:
            retry_after = headers.get("Retry-After")
            if retry_after:
                try:
                    return float(retry_after)
                except (TypeError, ValueError):
                    pass
        # Exponential backoff: base * 2**attempt.
        return self.retry_delay_seconds * (2 ** attempt)

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

    def append_blocks_idempotent(self, page_id: str, children: list[dict],
                                 dedup_key: str) -> Optional[dict]:
        """Append blocks at most once for a given (page, dedup_key).

        Guards against duplicate CFO page content when a webhook-triggered run
        and a scheduled batch run fire for the same period concurrently. The
        first caller to claim ``dedup_key`` performs the append; later callers
        with the same key become no-ops and return ``None``. ``dedup_key``
        should be timestamp/period-tagged (e.g. the analysis heading text).
        """
        store_key = f"{page_id}:{dedup_key}"
        # First writer wins; mark_done is atomic and does not overwrite.
        if not _writeback_store.mark_done(store_key):
            logger.info(f"Skipping duplicate write-back for {store_key!r}")
            return None
        return self.append_blocks(page_id, children)

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
