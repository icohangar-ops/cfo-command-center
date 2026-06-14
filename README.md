<div align="center">

# CFO Command Center

**AI-Powered Finance Operations Hub — Built on Notion.**

> **Note:** CFO Command Center is now the Notion dashboard layer for [ClosedLoop](https://github.com/icohangar-ops/closedloop). This repo provides the database schemas, sample data, and Notion integration scripts. The agent logic lives in ClosedLoop.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## What This Is

CFO Command Center transforms your Notion workspace into a real-time CFO dashboard. It provides 5 structured databases that surface agent outputs from ClosedLoop:

| Database | Purpose |
|----------|---------|
| **Vendor Scorecard** | Track and score vendor performance across your supply chain |
| **Cash Flow Forecast** | 13-week rolling forecast with auto-calculated formulas |
| **Working Capital Tracker** | DSO, DPO, DIO, CCC with trend analysis |
| **AP/AR Aging** | Aging analysis with action items and priority |
| **Payment Optimization Queue** | AI-ranked payment schedule to maximize discount capture |

---

## How It Connects to ClosedLoop

```
ClosedLoop Agents → Notion API → CFO Command Center Databases
                                        ↓
                                Notion Dashboard Views
                                        ↓
                                Board-Ready Reports
```

The Memory Agent in ClosedLoop writes decision rows to the Decision Log. CFO Command Center provides the visual layer that surfaces those decisions alongside real-time financial metrics.

---

## Quick Start

```bash
git clone https://github.com/icohangar-ops/cfo-command-center.git
cd cfo-command-center
cp .env.example .env
# Edit .env with your NOTION_TOKEN
pip install -r requirements.txt
python scripts/deploy_databases.py
python scripts/seed_sample_data.py
```

### Prerequisites

- Notion workspace with [Internal Integration](https://www.notion.so/my-integrations)
- Integration token with Read + Insert + Update capabilities
- Connected to your target Notion page

---

## Key Metrics at a Glance

| Metric | Current Value | Trend |
|--------|:------------:|:-----:|
| Cash Position | $2.65M | Improving |
| Cash Conversion Cycle (CCC) | 22 days | Down from 35 (Dec) |
| Net Working Capital | $2.35M | Up 30% in 6 months |
| Vendor Discount Capture | $3,070 identified | Per payment cycle |
| AR Overdue | $491K (3 invoices) | Needs attention |
| AP Overdue | $102K (3 invoices) | Needs attention |

---

## Database Schemas

Each database is deployed via the Notion API with full field definitions. See `scripts/deploy_databases.py` for the complete schema.

---

## License

MIT. See [`LICENSE`](./LICENSE).
