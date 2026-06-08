"""
src/config.py — Database IDs and constants loaded from .env
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Notion API
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28")

# Database IDs
DB_VENDOR_SCORECARD = os.getenv("DB_VENDOR_SCORECARD", "")
DB_CASH_FLOW_FORECAST = os.getenv("DB_CASH_FLOW_FORECAST", "")
DB_WORKING_CAPITAL = os.getenv("DB_WORKING_CAPITAL", "")
DB_AP_AR_AGING = os.getenv("DB_AP_AR_AGING", "")
DB_PAYMENT_OPTIMIZATION = os.getenv("DB_PAYMENT_OPTIMIZATION", "")

# Page IDs
PAGE_CFO_CENTER = os.getenv("PAGE_CFO_CENTER", "")

# Webhook
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Borrowing rate for early payment analysis (annualized)
BORROWING_RATE_ANNUAL = 0.065  # 6.5%
BORROWING_RATE_DAILY = BORROWING_RATE_ANNUAL / 365
