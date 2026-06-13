"""
CFO Command Center — Webhook Event Server

Listens for Notion webhook events (page updated, database changed)
and triggers the appropriate finance agent for event-driven analysis.

Usage:
    python -m src.webhook_server

    Or via gunicorn:
    gunicorn src.webhook_server:app -w 1 -b 0.0.0.0:8080
"""

import json
import logging
import hmac
import hashlib
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from src.config import WEBHOOK_PORT, WEBHOOK_SECRET, NOTION_TOKEN, PAGE_CFO_CENTER
from src.notion_client import NotionClient, get_title, get_select
from src.agents.working_capital import WorkingCapitalAgent
from src.agents.cash_flow import CashFlowAgent
from src.agents.payment_optimization import PaymentOptimizationAgent
from src.agents.vendor_risk import VendorRiskAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("webhook_server")


class WebhookHandler(BaseHTTPRequestHandler):
    """Handles incoming webhook POST requests from Notion."""

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Verify webhook signature
        signature = self.headers.get("X-Webhook-Signature", "")
        if WEBHOOK_SECRET and not self._verify_signature(body, signature):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid signature"}).encode())
            logger.warning("Webhook signature verification failed")
            return

        try:
            event = json.loads(body.decode())
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
            return

        # Process event asynchronously
        thread = threading.Thread(target=self._process_event, args=(event,), daemon=True)
        thread.start()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "accepted"}).encode())

    def do_GET(self):
        """Health check endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "healthy",
            "service": "CFO Command Center Webhook Server",
        }).encode())

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        if not WEBHOOK_SECRET:
            return True
        # Strip a common 'sha256=' prefix that webhook senders prepend.
        if signature.startswith("sha256="):
            signature = signature[len("sha256="):]
        expected = hmac.new(
            WEBHOOK_SECRET.encode(), body, digestmod=hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def _process_event(self, event: dict):
        """Route webhook event to the appropriate agent."""
        event_type = event.get("type", "unknown")
        logger.info(f"Processing webhook event: {event_type}")

        try:
            client = NotionClient(token=NOTION_TOKEN)

            if event_type == "page.updated":
                self._handle_page_updated(client, event)
            elif event_type == "database.changed":
                self._handle_database_changed(client, event)
            else:
                logger.info(f"Unhandled event type: {event_type}")

        except Exception as e:
            logger.error(f"Error processing event: {e}")

    def _handle_page_updated(self, client: NotionClient, event: dict):
        """Route page update events based on parent database."""
        page_id = event.get("page", {}).get("id")
        if not page_id:
            return

        page = client.get_page(page_id)
        parent_db = page.get("parent", {}).get("database_id")

        db_agents = {
            "working_capital": PAGE_CFO_CENTER,  # mapped via config
            "cash_flow": PAGE_CFO_CENTER,
            "payment_optimization": PAGE_CFO_CENTER,
            "vendor_scorecard": PAGE_CFO_CENTER,
        }

        if parent_db:
            logger.info(f"Page {page_id} updated in database {parent_db}")
            # Trigger appropriate agent based on which database changed
            self._trigger_agent_for_db(client, parent_db)

    def _handle_database_changed(self, client: NotionClient, event: dict):
        """Handle database-level change events."""
        db_id = event.get("database", {}).get("id")
        if db_id:
            logger.info(f"Database {db_id} changed")
            self._trigger_agent_for_db(client, db_id)

    def _trigger_agent_for_db(self, client: NotionClient, db_id: str):
        """Trigger the appropriate finance agent for a database change."""
        from src import config

        agent_map = {
            config.DB_WORKING_CAPITAL: ("Working Capital", lambda c: WorkingCapitalAgent(c).run()),
            config.DB_CASH_FLOW_FORECAST: ("Cash Flow", lambda c: CashFlowAgent(c).run()),
            config.DB_PAYMENT_OPTIMIZATION: ("Payment Optimization", lambda c: PaymentOptimizationAgent(c).run()),
            config.DB_VENDOR_SCORECARD: ("Vendor Risk", lambda c: VendorRiskAgent(c).run()),
        }

        if db_id in agent_map:
            name, agent_fn = agent_map[db_id]
            logger.info(f"Triggering {name} agent for database change")
            try:
                result = agent_fn(client)
                logger.info(f"{name} agent completed: {json.dumps({k: v for k, v in result.items() if k != 'recommendations'})}")
            except Exception as e:
                logger.error(f"{name} agent failed: {e}")
        else:
            logger.info(f"No agent mapped for database {db_id}")


def run_server(port: int = None):
    """Start the webhook server."""
    port = port or WEBHOOK_PORT
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    logger.info(f"Webhook server listening on port {port}")
    logger.info(f"Endpoints: POST /webhook (events), GET / (health check)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down webhook server")
        server.shutdown()


if __name__ == "__main__":
    run_server()
