# Finance Connectors: Xero & QuickBooks Integration

This document covers the integration of Xero and QuickBooks connectors into the CFO Command Center, detailing data flow, sync schedules, and field mappings to the five core Notion databases.

## 1. Xero Python SDK Integration

**Repository**: [XeroAPI/xero-python](https://github.com/XeroAPI/xero-python) (185 stars)

### Authentication & Setup

- Uses OAuth 2.0 with PKCE flow
- Store credentials in `.env`: `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_REDIRECT_URI`
- Token refresh is handled automatically by the SDK

### Data Pulled

| Data Type | Xero Endpoint | Description |
|-----------|---------------|-------------|
| AP Invoices | `/api.xro/2.0/Invoices` | Bills from vendors (filter: `Type=="ACCPAY"`) |
| AR Invoices | `/api.xro/2.0/Invoices` | Invoices to customers (filter: `Type=="ACCREC"`) |
| Bank Transactions | `/api.xro/2.0/BankTransactions` | Payments, transfers, spend/receive money |
| Contacts | `/api.xro/2.0/Contacts` | Vendor and customer master data |
| Bank Balances | `/api.xro/2.0/BankAccounts` | Current account balances |

### Example Usage

```python
from xero_python.api import Configuration, ApiClient
from xero_python.accounting import AccountingApi

config = Configuration(
    client_id=os.environ["XERO_CLIENT_ID"],
    client_secret=os.environ["XERO_CLIENT_SECRET"],
    redirect_uri=os.environ["XERO_REDIRECT_URI"],
    scopes=["accounting.transactions", "accounting.contacts", "accounting.settings"],
)

api_client = ApiClient(config)
accounting = AccountingApi(api_client)

# Fetch all unpaid AP invoices
invoices = accounting.get_invoices(
    tenant_id=TENANT_ID,
    where='Type=="ACCPAY" AND Status!="AUTHORISED"',
    order="DueDate ASC"
)
```

---

## 2. QuickBooks OAuth Integration

**Repository**: [intuit/oauth-pythonclient](https://github.com/intuit/oauth-pythonclient) (84 stars)

### Authentication & Setup

- OAuth 2.0 with authorization code flow
- Store credentials in `.env`: `QB_CLIENT_ID`, `QB_CLIENT_SECRET`, `QB_REDIRECT_URI`, `QB_REFRESH_TOKEN`
- Company ID stored separately: `QB_COMPANY_ID`

### Data Pulled

| Data Type | QuickBooks Endpoint | Description |
|-----------|---------------------|-------------|
| Bills (AP) | `/v3/company/{id}/query?query=SELECT * FROM Bill` | Vendor bills |
| Invoices (AR) | `/v3/company/{id}/query?query=SELECT * FROM Invoice` | Customer invoices |
| Payments | `/v3/company/{id}/query?query=SELECT * FROM Payment` | Received/paid amounts |
| Accounts | `/v3/company/{id}/query?query=SELECT * FROM Account` | Chart of accounts |
| Vendors | `/v3/company/{id}/query?query=SELECT * FROM Vendor` | Vendor master data |

### Example Usage

```python
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
import requests

auth_client = AuthClient(
    client_id=os.environ["QB_CLIENT_ID"],
    client_secret=os.environ["QB_CLIENT_SECRET"],
    redirect_uri=os.environ["QB_REDIRECT_URI"],
    environment="production",
)

# After obtaining access_token and refresh_token
COMPANY_ID = os.environ["QB_COMPANY_ID"]
headers = {
    "Authorization": f"Bearer {access_token}",
    "Accept": "application/json",
}

query = "SELECT * FROM Bill WHERE Balance > '0' ORDER BY DueDate ASC"
response = requests.get(
    f"https://quickbooks.api.intuit.com/v3/company/{COMPANY_ID}/query",
    headers=headers,
    params={"query": query}
)
```

---

## 3. Data Flow to Notion Databases

### The 5 Core Notion Databases

| Notion Database | Primary Data Source | Refresh Frequency |
|-----------------|---------------------|-------------------|
| **Vendor Scorecard** | Xero Contacts + QuickBooks Vendors | Weekly |
| **Cash Flow** | Xero Bank Transactions + QuickBooks Payments | Daily |
| **Working Capital** | Xero Invoices (AP/AR) + QuickBooks Bills/Invoices | Daily |
| **AP/AR Aging** | Xero Invoices (open) + QuickBooks Bills/Invoices (unpaid) | Daily |
| **Payment Queue** | Xero Bank Transactions + QuickBooks Payments | Real-time |

### Sync Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Xero API  │────▶│  Sync Service   │────▶│  Notion API     │
└─────────────┘     │                 │     │                 │
                    │  - Normalize    │     │  - Vendor Score │
┌─────────────┐     │  - Map fields   │     │  - Cash Flow    │
│ QuickBooks  │────▶│  - Queue sync   │     │  - Working Cap  │
│     API     │     │  - Retry logic  │     │  - AP/AR Aging  │
└─────────────┘     └─────────────────┘     │  - Payment Queue│
                                            └─────────────────┘
```

---

## 4. Sync Schedule

| Task | Frequency | Time (UTC) | Description |
|------|-----------|------------|-------------|
| **Daily Invoice Sync** | Every day | 02:00 | Pull all new/modified invoices from Xero & QuickBooks; update AP/AR Aging and Working Capital databases |
| **Weekly Payment Reconciliation** | Every Monday | 04:00 | Match bank transactions against invoices; update Cash Flow and Payment Queue; recalculate Vendor Scorecard metrics |
| **Monthly Close Data Pull** | 1st of month | 06:00 | Full snapshot of all open items; generate period-end reports; update all 5 databases with closing balances |

### Additional Triggers

- **Webhook events** (Xero): Real-time invoice/payment status changes
- **Manual refresh**: API endpoint `/api/sync/trigger` for on-demand pulls
- **Error retry**: Failed syncs retry 3x with exponential backoff (1m, 5m, 15m)

---

## 5. Data Mapping

### Xero → Notion Field Mapping

| Xero Field | Notion Database | Notion Field | Transform |
|------------|-----------------|--------------|-----------|
| `Invoice.InvoiceID` | All | `Source ID` | Prefix `xero_` |
| `Invoice.InvoiceNumber` | AP/AR Aging | `Invoice #` | Direct |
| `Invoice.Type` | AP/AR Aging | `Type` | `ACCPAY` → "AP", `ACCREC` → "AR" |
| `Invoice.Contact.Name` | Vendor Scorecard | `Vendor/Customer` | Direct |
| `Invoice.Total` | Working Capital, AP/AR Aging | `Amount` | Decimal, 2 places |
| `Invoice.AmountDue` | AP/AR Aging | `Balance Due` | Decimal, 2 places |
| `Invoice.DueDate` | AP/AR Aging, Payment Queue | `Due Date` | ISO 8601 |
| `Invoice.Status` | AP/AR Aging | `Status` | Map: `AUTHORISED` → "Open", etc. |
| `BankTransaction.Amount` | Cash Flow | `Amount` | Decimal, 2 places |
| `BankTransaction.Type` | Cash Flow | `Category` | `SPEND` → "Outflow", `RECEIVE` → "Inflow" |
| `BankTransaction.Date` | Cash Flow | `Date` | ISO 8601 |
| `BankTransaction.Reference` | Payment Queue | `Reference` | Direct |
| `Contact.Name` | Vendor Scorecard | `Name` | Direct |
| `Contact.Balance` | Vendor Scorecard | `Outstanding Balance` | Decimal |
| `Contact.DefaultCurrency` | Vendor Scorecard | `Currency` | ISO 4217 |

### QuickBooks → Notion Field Mapping

| QuickBooks Field | Notion Database | Notion Field | Transform |
|------------------|-----------------|--------------|-----------|
| `Bill.Id` | All | `Source ID` | Prefix `qb_` |
| `Bill.DocNumber` | AP/AR Aging | `Invoice #` | Direct |
| `Bill.EntityRef.name` | Vendor Scorecard | `Vendor/Customer` | Direct |
| `Bill.TotalAmt` | Working Capital, AP/AR Aging | `Amount` | Decimal, 2 places |
| `Bill.Balance` | AP/AR Aging | `Balance Due` | Decimal, 2 places |
| `Bill.DueDate` | AP/AR Aging, Payment Queue | `Due Date` | ISO 8601 |
| `Bill.TxnDate` | Cash Flow | `Date` | ISO 8601 |
| `Payment.TotalAmt` | Cash Flow | `Amount` | Decimal, 2 places |
| `Payment.TxnDate` | Cash Flow | `Date` | ISO 8601 |
| `Payment.ReferenceNum` | Payment Queue | `Reference` | Direct |
| `Account.Name` | Cash Flow | `Account` | Direct |
| `Account.AccountSubType` | Cash Flow | `Category` | Map to Cash Flow categories |

---

## Environment Variables

Add these to `.env`:

```env
# Xero
XERO_CLIENT_ID=your_client_id
XERO_CLIENT_SECRET=your_client_secret
XERO_REDIRECT_URI=http://localhost:8000/auth/xero/callback
XERO_TENANT_ID=your_tenant_id
XERO_ACCESS_TOKEN=auto_refreshed
XERO_REFRESH_TOKEN=auto_refreshed

# QuickBooks
QB_CLIENT_ID=your_client_id
QB_CLIENT_SECRET=your_client_secret
QB_REDIRECT_URI=http://localhost:8000/auth/quickbooks/callback
QB_COMPANY_ID=your_company_id
QB_ACCESS_TOKEN=auto_refreshed
QB_REFRESH_TOKEN=auto_refreshed

# Notion
NOTION_API_KEY=your_notion_integration_key
NOTION_VENDOR_SCORECARD_DB=your_database_id
NOTION_CASH_FLOW_DB=your_database_id
NOTION_WORKING_CAPITAL_DB=your_database_id
NOTION_AP_AR_AGING_DB=your_database_id
NOTION_PAYMENT_QUEUE_DB=your_database_id
```

---

## Dependencies

Add to `requirements.txt`:

```
xero-python>=4.3.0
intuitlib>=1.0.0
notion-client>=2.0.0
```
