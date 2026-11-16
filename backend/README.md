# PROMED API

The backend is a local FastAPI service backed by SQLite. On startup it safely migrates existing tables, idempotently seeds the nine configured Shopping Zone categories, and inserts only the four configured inventory locations (`A1`, `A2`, `B1`, `B2`). Product, batch, transaction, sales and order records are created through API requests; the frontend demo dataset is not loaded by the application.

## Run locally

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal, serve the frontend from the repository root:

```powershell
python -m http.server 5500 --bind 127.0.0.1
```

Open `http://127.0.0.1:5500/`. Interactive API documentation is available at `http://127.0.0.1:8000/docs`; health is checked at `/api/health`.

The default SQLite file is `backend/data/promed.sqlite3`. Set `PROMED_DATABASE_URL` to use another SQLAlchemy database URL. `PROMED_CORS_ORIGINS` is a comma-separated origin allow-list; its default permits the two local frontend URLs above. Keep Uvicorn bound to loopback until a deployment security review is complete.

On a new database, create the first staff owner from the repository root:

```powershell
python -m backend.app.create_owner
```

The command prompts for the owner email, display name and password; it does not accept or store a plaintext password. Sign in at the existing `index.html` staff entry. Owners can provision pharmacist and operator accounts through `POST /api/auth/staff/users`. Customer registration is separate and cannot grant a staff role.

## Data model

- `product_categories`: unique normalized name and slug, description, local image path, active status, and product relationship. Startup seeds the nine Shopping Zone categories without duplicating or deleting category records.
- `products`: product catalog, unique optional barcode, threshold, selling price, unit of measure, prescription and active flags, and optional pharmacist-reviewed customer-facing label details.
- `inventory_locations`: seeded and operator-configurable storage locations.
- `suppliers`: supplier name, contact details, address, and optional reference.
- `medicine_batches`: per-location batch balances, manufacturing/expiry and purchase dates, supplier, purchase price, unit cost, received and available quantities, and operational status.
- `stock_transactions`: append-only receipt, adjustment, and sale quantity deltas, including previous and updated batch quantities.
- `batch_status_events`: reasoned, timestamped status changes for quarantine and damage traceability.
- `sales` and `sale_items`: invoice snapshots, configured taxes/discounts, and exact batch-level FEFO allocations.
- `payment_records`: recorded cash, UPI or card payments and refunds. No payment gateway is connected.
- `sale_returns` and `sale_return_items`: return/refund history, returned quantities, disposition, and inspection reference when stock is restocked.
- `account_users` and `user_sessions`: customer/staff roles, PBKDF2-SHA256 password hashes, and hashed, revocable session tokens.
- `orders` and `order_items`: optional customer ownership, fulfillment, idempotency, workflow and price/total snapshots; order creation does not reserve or deduct stock.
- `order_status_events` and `prescription_verifications`: auditable workflow and pharmacist-review history.
- `store_configuration`: explicitly configured store identity, currency and tax percentage for POS invoices.
- `application_settings`: operational key/value settings; do not store credentials here.

Foreign keys, uniqueness rules, positive/nonnegative quantity and amount checks, and indexes are defined in the SQLAlchemy models. FEFO sale allocation uses the earliest-expiring active, unexpired batches first; quarantined and damaged batches are ineligible, and insufficient eligible stock rejects the entire sale. Product lookup and barcode search do not alter quantities. Physical on-hand totals include every batch; sellable totals exclude expired, quarantined, and damaged quantities.

The SQLite startup migrations add stock snapshots and Stage 4 batch fields first, then Stage 5 sales/order fields, Stage 6 customer ownership and product facts, and Stage 7 category metadata and product units. They preserve existing records and history. Legacy order status constraints remain unchanged; a separate workflow status supports the richer order lifecycle. Receipt, adjustment, checkout, return, and FEFO stock operations use database transactions and guarded updates. Expired stock remains recorded and is excluded from sale allocation. Customer catalog availability includes only active products in active categories with active, unexpired, positive-quantity batches, and never exposes batch, location, supplier, purchase-cost or margin records. Customer order creation validates available stock in a serialized SQLite write transaction, snapshots price and creates no stock transaction. Staff rechecks customer order quantities before acceptance; actual stock remains controlled by the existing FEFO sale workflow.

The owner-only Product Management workspace is available from the dashboard after owner sign-in. It supports category and product search/filtering, product edits and activation, optional product label information, product image preview/replacement/removal, and optional initial batch receipt. Initial stock goes through the existing receipt service and stock ledger in the same database transaction as product creation; leaving initial stock unchecked creates no batch. Purchase price and unit cost are recorded per batch, not as customer-visible product fields. Upload accepts JPG/JPEG, PNG and WebP image content up to 5 MB and 20 megapixels, verifies and re-encodes images to WebP, and assigns a generated filename under `assets/products/<category-slug>/`. Keep the frontend static server running from the repository root so these local image paths resolve. Uploaded product photos are local application data and should be backed up with the SQLite database.

The main entry page provides separate staff/owner sign-in and customer Shopping Zone options. Analytics and report APIs are owner-only on the backend; hiding the navigation item for other staff roles is only a usability measure, not the authorization boundary.

Owner analytics supports date-filtered sales, returns, average transaction value, product/category performance, inventory and eligible stock, low stock, expiry exposure, supplier batch purchase records, customer order workflow, and stock movement. Reports can be searched, sorted, filtered by category where applicable, and exported as CSV or PDF. The date range is limited to three years and detailed exports are capped at 5,000 rows. The dashboard uses configured currency only; it does not assume one.

Gross profit is explicitly an estimate: the database stores batch unit cost but does not snapshot cost on each sale item. A profit value is withheld when any sold units lack recorded cost, and the dashboard notes that a later batch cost update can affect historical estimates. Inventory value is marked incomplete when any on-hand units lack recorded cost. Supplier purchase reports use the batch's recorded purchase price; separate receipt-level price history and a purchase-order workflow are not stored, so pending purchase orders and exact receipt-by-receipt spend cannot be reported.

All existing inventory, sales, dashboard, settings and staff order APIs require a staff session. Staff roles are owner, pharmacist and operator; prescription review is limited to owner/pharmacist, and operators do not receive prescription references or review history. Customer accounts use separate HttpOnly, SameSite=Lax cookies. Passwords are PBKDF2-SHA256 hashed; session tokens are random and only their hashes are stored. Customer order and tracking endpoints are scoped to the signed-in customer. The local CORS allow-list and loopback run command are not a substitute for deployment controls; email verification, login rate limiting, MFA and production TLS/session-secret management are not included.

Paid POS checkout requires `PUT /api/sales/config` to explicitly set store name, contact phone, currency code, and tax percentage. There is no assumed tax rate. Checkout prices are taken from product records, and totals are recomputed server-side using decimal arithmetic. Prescription documents are not collected; prescription-required orders are marked for pharmacist review and cannot be accepted until reviewed. No payment gateway or delivery partner is connected. Store hours and fulfilment service availability still require configuration and staff confirmation.

Low-stock products are those with positive configured minimums and stock at or below that threshold. Suggested reorder quantity targets twice the minimum threshold (`2 × minimum − current stock`); this is a planning heuristic, not a supplier purchase order.

## REST endpoints

All routes are prefixed with `/api`; JSON validation errors use HTTP 422, missing resources use 404, and uniqueness/business conflicts use 409. Legacy management routes require a staff cookie; customer catalog routes are public and customer-order routes require a customer cookie.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Verify API and database connectivity |
| POST | `/auth/customer/register` | Register a customer and start a customer session |
| POST | `/auth/customer/login` | Sign in a customer |
| GET, PATCH | `/auth/customer/me` | Read or update the signed-in customer's name and phone |
| POST | `/auth/customer/logout` | Revoke the current customer session |
| POST | `/auth/staff/login` | Sign in an owner, pharmacist, or operator |
| GET | `/auth/staff/me` | Read the signed-in staff account |
| POST | `/auth/staff/logout` | Revoke the current staff session |
| POST | `/auth/staff/users` | Owner-only creation of pharmacist or operator accounts |
| GET | `/store/catalog/categories` | List the nine storefront categories independently of inventory, plus custom categories used by active products |
| GET | `/store/catalog/status` | Return aggregate active-product, eligible-product, and configured-category counts for accurate empty-catalog messaging |
| GET | `/store/catalog/products` | Safe customer catalog; supports `q`, exact `barcode`, `category_id` or a store-category slug, `available`, `sort`, and `limit` |
| POST | `/customer/orders` | Create an authenticated pickup/delivery order without stock deduction or reservation |
| GET | `/customer/orders` | List the signed-in customer's orders |
| GET | `/customer/orders/{order_id}` | Retrieve one of the signed-in customer's orders |
| GET | `/customer/orders/by-number/{order_number}` | Track an order by number, scoped to the signed-in customer |
| POST | `/customer/orders/{order_id}/cancel` | Cancel a customer order before staff acceptance |
| GET, POST | `/categories` | List or create a category |
| PATCH | `/categories/{category_id}` | Owner-only category name, description, image path, or active status update |
| GET, POST | `/locations` | List or create configured inventory locations |
| PUT | `/locations/{location_id}` | Update a location code or name |
| GET, POST | `/products` | Search/list products or create a product |
| GET | `/products/{product_id}` | Retrieve a product, its batches, and current stock |
| PATCH | `/products/{product_id}` | Update the product's minimum stock threshold |
| GET | `/management/products` | Owner-only product search/list, including inactive products; accepts `q`, `category_id`, `active`, and `limit` |
| POST | `/management/products` | Owner-only full product creation with optional atomic initial batch receipt |
| PATCH | `/management/products/{product_id}` | Owner-only product details, category, price, prescription and active-status update |
| POST | `/management/products/{product_id}/image` | Owner-only raw image upload; set `Content-Type` to `image/jpeg`, `image/png`, or `image/webp` |
| DELETE | `/management/products/{product_id}/image` | Owner-only image removal |
| POST | `/inventory/receipts` | Add received units to a dated batch and record a ledger entry |
| POST | `/inventory/adjustments` | Apply a nonzero batch quantity delta with a reason |
| GET | `/inventory/transactions` | List stock ledger entries; accepts `product_id` and `limit` |
| GET | `/inventory/low-stock` | List low-stock products and suggested reorder quantities |
| GET | `/inventory/batches` | List batches with product, batch, date, category, location, status, and expiry-category filters |
| GET | `/inventory/batches/{batch_id}` | Retrieve batch metadata and current physical/sellable quantities |
| GET | `/inventory/batches/{batch_id}/history` | Retrieve batch stock transactions and status-change history |
| PATCH | `/inventory/batches/{batch_id}/status` | Change a batch to active, quarantined, or damaged with a required reason |
| GET | `/inventory/expiry` | List in-stock batches expiring by `within_days` (default 30); supports the batch filters |
| GET, POST | `/suppliers` | List or create supplier records |
| PATCH | `/suppliers/{supplier_id}` | Update supplier contact and reference details |
| GET | `/dashboard` | Calculate stock availability, expiry categories, low-stock, location, sales, and transaction summaries |
| GET | `/analytics/dashboard` | Owner-only date-filtered sales, profit coverage, inventory, expiry, order and purchase summary |
| GET | `/analytics/reports/{report_type}` | Owner-only searchable/sortable report data; supports `date_from`, `date_to`, `search`, `category`, `sort_by`, and `direction` |
| GET | `/analytics/reports/{report_type}/export` | Owner-only CSV or PDF export using `format=csv|pdf` and the report filters |
| GET | `/sales/config` | Read explicit store, tax and currency configuration |
| PUT | `/sales/config` | Save store identity, currency and configured tax rate |
| GET | `/sales/summary` | Return database-derived daily, weekly, monthly, best-seller and recent-invoice statistics |
| GET | `/sales/history` | Search invoices by invoice number or customer phone |
| GET | `/sales/returns` | List return history; optional invoice-number filter |
| GET | `/sales/returns/{return_id}` | Retrieve a return and refund record |
| GET, POST | `/sales` | List sales or retain the legacy FEFO stock-issue API |
| POST | `/sales/checkout` | Validate payment, allocate eligible batches by FEFO, deduct stock atomically, and record invoice/payment |
| GET | `/sales/{sale_id}/invoice` | Retrieve saved invoice details |
| GET | `/sales/{sale_id}/invoice.pdf` | Download a generated invoice PDF |
| GET | `/sales/{sale_id}/returns` | List returns for an invoice |
| POST | `/sales/{sale_id}/returns` | Record a return/refund; restocking is opt-in and requires inspection reference |
| GET, POST | `/orders` | Preserve legacy order list/create behavior without stock reservation |
| POST | `/orders/workflow` | Create a pickup/delivery order without stock reservation |
| GET | `/orders/workflow` | List managed orders; accepts `status`, `customer_phone`, and `limit` |
| GET | `/orders/{order_id}/workflow` | Retrieve order details and status/prescription history |
| PATCH | `/orders/{order_id}/workflow` | Apply an allowed order status transition |
| PATCH | `/orders/{order_id}/prescription` | Record pharmacist verification or rejection during review |
| PATCH | `/orders/{order_id}` | Preserve the legacy pending/fulfilled/cancelled status endpoint |
| GET | `/settings` | List operational settings |
| PUT | `/settings/{key}` | Create or update an operational setting |

Product creation accepts either `category_id` or `category_name`, can mark prescription status, and optionally records manufacturer, local image path, description, ingredients, uses, directions and warnings. Product Management uses a database category selection and supports generated-name image uploads. Label details are shown to customers only when the record is explicitly marked pharmacist-verified; no missing medical facts are inferred. Search accepts `q`, exact `barcode`, and/or `location_code`; these lookups never change stock. Receipts accept optional manufacturing date, purchase date, supplier, purchase price, and unit cost in addition to product, batch, expiry, quantity, and location. Receipt, adjustment, sale, and verified-restock writes create stock transaction records in the same database transaction. Dashboard expiry categories are disjoint: expired, 0–30, 31–60, 61–90, and more than 90 days remaining. Managed orders use `RECEIVED`, `PHARMACIST_REVIEW`, `ACCEPTED`, `PREPARING`, `READY_FOR_PICKUP`, `OUT_FOR_DELIVERY`, `COMPLETED`, `REJECTED`, and `CANCELLED`; transitions are validated and customer orders do not reserve or deduct stock. Without stock reservation, stock may change after order submission; staff revalidation and the existing transactional FEFO sale flow remain necessary.

Analytics report types are `sales`, `revenue`, `profit`, `product-performance`, `inventory`, `inventory-by-location`, `low-stock`, `expiry`, `supplier-purchases`, `customer-orders`, and `stock-movement`.

To enter the first real product, sign in at the owner dashboard, open **Product Management**, select one of the configured categories, enter the recorded name and selling price, and leave unrecorded optional fields blank. To stock it immediately, enable **Receive initial stock now** and enter its batch number, expiry, quantity, and storage location; manufacturing date, supplier, purchase price and unit cost are optional when unknown. Save the product. If no stock is received, the product remains unavailable to customers until a valid receipt is recorded. Do not enter assumed label information or use an unverified brand image.

## Tests

Run backend tests from the repository root:

```powershell
python -m pytest backend/tests
```
