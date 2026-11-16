/**
 * PROMED frontend application and API-backed inventory workflows.
 */
class PromedApplication {
  constructor() {
    this.nav = null;
    this.dashboard = null;
    this.productManagement = null;
    this.reports = null;
    this.products = [];
    this.locations = [];
    this.categories = [];
    this.suppliers = [];
    this.salesConfig = null;
    this.posCart = [];
    this.orderItems = [];
    this.workspaceInitialized = false;
    this.staffRole = null;
    this.posSearchTimer = null;
    this.barcodeModal = document.getElementById('barcodeModal');
    this.barcodeInput = document.getElementById('modalBarcodeInput');
    this.barcodeResult = document.getElementById('barcodeResultCard');
    this.barcodeLookupBtn = document.getElementById('barcodeLookupBtn');
    this.batchDetailsModal = document.getElementById('batchDetailsModal');
    this.batchDetailsContent = document.getElementById('batchDetailsContent');
  }

  async init() {
    this.setupStaffAccess();
    try {
      const staff = await PromedApi.get('/auth/staff/me');
      if (!staff) {
        document.getElementById('staffSignIn').hidden = false;
        document.getElementById('staffLoginStatus').textContent =
          'Sign in to access management features.';
        return;
      }
      await this.startWorkspace(staff);
    } catch (error) {
      document.getElementById('staffSignIn').hidden = false;
      document.getElementById('staffLoginStatus').textContent =
        `Sign in to access management features. ${error.message}`;
      document.getElementById('staffLoginStatus').classList.add('is-error');
    }
  }

  setupStaffAccess() {
    document.getElementById('staffLoginForm')?.addEventListener('submit', async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const fields = new FormData(form);
      const status = document.getElementById('staffLoginStatus');
      status.textContent = 'Signing in...';
      status.classList.remove('is-error');
      try {
        const staff = await PromedApi.post('/auth/staff/login', {
          email: fields.get('email'),
          password: fields.get('password')
        });
        form.reset();
        await this.startWorkspace(staff);
      } catch (error) {
        status.textContent = error.message;
        status.classList.add('is-error');
      }
    });

    document.getElementById('staffLogoutBtn')?.addEventListener('click', async () => {
      try {
        await PromedApi.post('/auth/staff/logout', {});
        document.getElementById('staffApp').hidden = true;
        document.getElementById('staffSignIn').hidden = false;
        document.getElementById('staffLoginStatus').textContent = 'You have signed out.';
        document.getElementById('staffLoginStatus').classList.remove('is-error');
      } catch (error) {
        this.showStatus(error.message, true);
      }
    });
  }

  async startWorkspace(staff) {
    document.getElementById('staffSignIn').hidden = true;
    document.getElementById('staffApp').hidden = false;
    document.getElementById('staffAccountName').textContent =
      `${staff.display_name} · ${staff.role}`;
    this.staffRole = staff.role;
    if (!this.reports) this.reports = new PromedReports();
    this.reports.init(staff.role);
    if (this.workspaceInitialized) return;
    this.workspaceInitialized = true;
    this.nav = new PromedNavigation();
    this.dashboard = new PromedDashboard(this);
    this.setupQuickActions();
    this.setupBarcodeModal();
    this.setupBatchDetailsModal();
    this.setupInventoryForms();
    this.setupSalesWorkflows();
    this.setupOrderWorkflows();
    this.productManagement = new PromedProductManagement();

    const results = await Promise.allSettled([
      this.dashboard.refresh(),
      this.productManagement.init(this.staffRole),
      ...(this.staffRole === 'owner' ? [this.reports.load()] : []),
      this.loadInventory(),
      this.loadLowStock(),
      this.loadExpiry(),
      this.loadSales(),
      this.loadOrders(),
      this.loadSalesConfig()
    ]);
    results.filter(result => result.status === 'rejected')
      .forEach(result => this.showStatus(result.reason.message, true));
  }

  setupQuickActions() {
    document.getElementById('btnQuickOpenInventory')?.addEventListener('click', () => {
      this.nav.navigateTo('inventory');
    });

    document.getElementById('btnQuickScanBarcode')?.addEventListener('click', () => {
      this.openBarcodeModal();
    });

    document.getElementById('btnScanOpenModal')?.addEventListener('click', () => {
      this.openBarcodeModal();
    });

    document.querySelector('.nav-link[data-view="expiry"]')?.addEventListener('click', () => {
      this.loadExpiry().catch(error => this.showStatus(error.message, true, 'expiryStatus'));
    });

    document.getElementById('refreshExpiryBtn')?.addEventListener('click', () => {
      this.loadExpiry().catch(error => this.showStatus(error.message, true, 'expiryStatus'));
    });

    document.getElementById('batchFilterForm')?.addEventListener('submit', event => {
      event.preventDefault();
      this.loadExpiry().catch(error => this.showStatus(error.message, true, 'expiryStatus'));
    });

    document.getElementById('clearBatchFiltersBtn')?.addEventListener('click', () => {
      document.getElementById('batchFilterForm')?.reset();
      this.loadExpiry().catch(error => this.showStatus(error.message, true, 'expiryStatus'));
    });

    document.querySelector('.nav-link[data-view="reorder"]')?.addEventListener('click', () => {
      this.loadLowStock().catch(error => this.showStatus(error.message, true, 'lowStockStatus'));
    });

    document.getElementById('refreshLowStockBtn')?.addEventListener('click', () => {
      this.loadLowStock().catch(error => this.showStatus(error.message, true, 'lowStockStatus'));
    });

    document.querySelector('.nav-link[data-view="sales"]')?.addEventListener('click', () => {
      this.loadSales().catch(error => this.showStatus(error.message, true, 'salesStatus'));
    });

    document.querySelector('.nav-link[data-view="orders"]')?.addEventListener('click', () => {
      this.loadOrders().catch(error => this.showStatus(error.message, true, 'ordersStatus'));
    });

    document.querySelector('.nav-link[data-view="settings"]')?.addEventListener('click', () => {
      this.loadSalesConfig().catch(error => this.showStatus(error.message, true, 'salesConfigStatus'));
    });
  }

  setupBarcodeModal() {
    if (!this.barcodeModal) return;

    this.barcodeModal.querySelectorAll('[data-close-modal]').forEach(button => {
      button.addEventListener('click', () => this.closeBarcodeModal());
    });

    this.barcodeModal.addEventListener('click', event => {
      if (event.target === this.barcodeModal) this.closeBarcodeModal();
    });

    this.barcodeLookupBtn?.addEventListener('click', () => {
      this.performBarcodeLookup(this.barcodeInput.value.trim());
    });

    this.barcodeInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        this.performBarcodeLookup(this.barcodeInput.value.trim());
      }
    });

    document.querySelectorAll('.barcode-chip').forEach(button => {
      button.addEventListener('click', () => this.openBarcodeModal(button.dataset.barcode || ''));
    });
  }

  openBarcodeModal(presetBarcode = '') {
    if (!this.barcodeModal) return;
    this.barcodeModal.classList.add('active');

    if (presetBarcode) {
      this.barcodeInput.value = presetBarcode;
      this.performBarcodeLookup(presetBarcode);
    } else {
      this.barcodeInput.value = '';
      this.barcodeResult.replaceChildren();
      this.barcodeResult.classList.remove('active');
    }

    setTimeout(() => this.barcodeInput?.focus(), 100);
  }

  closeBarcodeModal() {
    this.barcodeModal?.classList.remove('active');
  }

  async performBarcodeLookup(barcode) {
    if (!barcode) {
      this.renderBarcodeMessage('Enter a barcode to search the product catalog.');
      return;
    }
    try {
      const products = await PromedApi.get(`/products?barcode=${encodeURIComponent(barcode)}`);
      if (products.length === 0) {
        this.renderBarcodeMessage('No product was found for this barcode.');
        return;
      }
      this.renderProductDetails(products[0]);
    } catch (error) {
      this.renderBarcodeMessage(error.message, true);
    }
  }

  async openProduct(productId) {
    try {
      const product = await PromedApi.get(`/products/${productId}`);
      this.barcodeModal.classList.add('active');
      this.barcodeInput.value = product.barcode || '';
      this.renderProductDetails(product);
    } catch (error) {
      this.showStatus(error.message, true);
    }
  }

  renderProductDetails(product) {
    const batches = product.batches.length
      ? product.batches.map(batch => `
          <tr>
            <td>${this.escapeHtml(batch.batch_number)}</td>
            <td>${this.escapeHtml(batch.expiry_category.replace(/_/g, ' '))}</td>
            <td>${this.escapeHtml(batch.expiry_date)}</td>
            <td>${this.escapeHtml(batch.location_code)}</td>
            <td>${batch.quantity.toLocaleString()} / ${batch.available_quantity.toLocaleString()}</td>
            <td>${this.escapeHtml(batch.status)}</td>
          </tr>
        `).join('')
      : '<tr><td colspan="6" class="empty-state">No stock batches have been received.</td></tr>';

    this.barcodeResult.innerHTML = `
      <div class="barcode-result-header">
        <span class="badge-status badge-status-in-stock">Product record</span>
      </div>
      <div class="barcode-medicine-name">${this.escapeHtml(product.name)}</div>
      <p class="section-description">${this.escapeHtml(product.generic_name || 'No generic name')} · ${this.escapeHtml(product.category_name)}</p>
      <p class="section-description">Barcode: ${this.escapeHtml(product.barcode || 'Not set')} · On hand: ${product.stock_quantity.toLocaleString()} units · Sellable: ${product.available_stock_quantity.toLocaleString()} · Expired: ${product.expired_stock_quantity.toLocaleString()} · Price: ${this.formatMoney(product.unit_price, this.salesConfig?.currency_code)}</p>
      <div class="table-responsive batch-table">
        <table class="promed-table">
          <thead><tr><th>Batch</th><th>Expiry status</th><th>Expiry</th><th>Location</th><th>On hand / sellable</th><th>Status</th></tr></thead>
          <tbody>${batches}</tbody>
        </table>
      </div>
    `;
    this.barcodeResult.classList.add('active');
  }

  renderBarcodeMessage(message, isError = false) {
    this.barcodeResult.innerHTML = `<p class="${isError ? 'form-error' : 'empty-state'}">${this.escapeHtml(message)}</p>`;
    this.barcodeResult.classList.add('active');
  }

  async loadInventory() {
    const [products, locations, transactions, categories, suppliers] = await Promise.all([
      PromedApi.get('/products'),
      PromedApi.get('/locations'),
      PromedApi.get('/inventory/transactions?limit=100'),
      PromedApi.get('/categories'),
      PromedApi.get('/suppliers')
    ]);
    this.products = products;
    this.locations = locations;
    this.categories = categories;
    this.suppliers = suppliers;
    this.renderInventory(products);
    this.renderTransactions(transactions);
    this.populateInventoryForms();
    this.populateOrderProductOptions();
  }

  async loadLowStock() {
    const products = await PromedApi.get('/inventory/low-stock');
    const tableBody = document.getElementById('lowStockTableBody');
    if (!products.length) {
      tableBody.innerHTML = '<tr><td colspan="7" class="empty-state">No products are at or below their minimum stock level.</td></tr>';
      this.showStatus('Low-stock data refreshed.', false, 'lowStockStatus');
      return;
    }

    tableBody.innerHTML = products.map(product => {
      const locationQuantities = product.location_quantities.length
        ? product.location_quantities.map(item =>
          `${this.escapeHtml(item.location_code)}: ${item.quantity.toLocaleString()}`
        ).join(', ')
        : '—';
      return `
        <tr>
          <td><strong>${this.escapeHtml(product.product_name)}</strong></td>
          <td class="text-mono">${this.escapeHtml(product.barcode || '—')}</td>
          <td>${product.stock_quantity.toLocaleString()}</td>
          <td>${product.min_threshold.toLocaleString()}</td>
          <td><strong>${product.suggested_reorder_quantity.toLocaleString()}</strong></td>
          <td>${locationQuantities}</td>
          <td><button class="btn btn-secondary btn-sm" type="button" data-product-id="${product.product_id}">View</button></td>
        </tr>
      `;
    }).join('');
    tableBody.querySelectorAll('[data-product-id]').forEach(button => {
      button.addEventListener('click', () => this.openProduct(Number(button.dataset.productId)));
    });
    this.showStatus(`${products.length} low-stock product(s) found.`, false, 'lowStockStatus');
  }

  async loadExpiry() {
    const form = document.getElementById('batchFilterForm');
    const params = new URLSearchParams();
    if (form) {
      new FormData(form).forEach((value, key) => {
        if (String(value).trim()) params.set(key, String(value).trim());
      });
    }
    params.set('limit', '500');
    const batches = await PromedApi.get(`/inventory/batches?${params.toString()}`);
    const tableBody = document.getElementById('expiryTableBody');
    if (!tableBody) return;
    if (!batches.length) {
      tableBody.innerHTML = '<tr><td colspan="12" class="empty-state">No batches match the selected filters.</td></tr>';
      this.showStatus('Batch data refreshed.', false, 'expiryStatus');
      return;
    }

    tableBody.innerHTML = batches.map(batch => {
      const expiryStatus = batch.days_remaining < 0
        ? `Expired ${Math.abs(batch.days_remaining)} day(s) ago`
        : batch.days_remaining === 0 ? 'Expires today' : `${batch.days_remaining} day(s)`;
      const badgeClass = batch.expiry_category === 'expired' || batch.expiry_category === 'within_30_days'
        ? 'badge-status-low-stock'
        : batch.expiry_category === 'safe' ? 'badge-status-in-stock' : 'badge-status-expiring';
      return `
        <tr>
          <td><strong>${this.escapeHtml(batch.product_name)}</strong><div class="subtle-text">${this.escapeHtml(batch.category_name)} · ${this.escapeHtml(batch.barcode || 'No barcode')}</div></td>
          <td>${this.escapeHtml(batch.batch_number)}</td>
          <td>${this.escapeHtml(batch.manufacturing_date || '—')}</td>
          <td>${this.escapeHtml(batch.expiry_date)}</td>
          <td><span class="badge-status ${badgeClass}">${this.escapeHtml(expiryStatus)}</span><div class="subtle-text">${this.escapeHtml(batch.expiry_category.replace(/_/g, ' '))}</div></td>
          <td>${this.escapeHtml(batch.supplier_name || '—')}</td>
          <td>${this.escapeHtml(batch.purchase_date)}</td>
          <td>${batch.received_quantity.toLocaleString()}</td>
          <td>${batch.quantity.toLocaleString()} / ${batch.available_quantity.toLocaleString()}</td>
          <td>${batch.unit_cost === null ? '—' : this.formatMoney(batch.unit_cost, this.salesConfig?.currency_code)}</td>
          <td>${this.escapeHtml(batch.location_code)}</td>
          <td><span class="badge-status ${batch.status === 'active' ? 'badge-status-in-stock' : 'badge-status-low-stock'}">${this.escapeHtml(batch.status)}</span> <button class="btn btn-secondary btn-sm" type="button" data-batch-id="${batch.id}">Details</button></td>
        </tr>
      `;
    }).join('');
    tableBody.querySelectorAll('[data-batch-id]').forEach(button => {
      button.addEventListener('click', () => this.openBatchDetails(Number(button.dataset.batchId)));
    });
    this.showStatus(`${batches.length} batch(es) found.`, false, 'expiryStatus');
  }

  setupBatchDetailsModal() {
    if (!this.batchDetailsModal) return;
    this.batchDetailsModal.querySelectorAll('[data-close-batch-modal]').forEach(button => {
      button.addEventListener('click', () => this.closeBatchDetails());
    });
    this.batchDetailsModal.addEventListener('click', event => {
      if (event.target === this.batchDetailsModal) this.closeBatchDetails();
    });
    this.batchDetailsModal.addEventListener('keydown', event => {
      if (event.key === 'Escape') this.closeBatchDetails();
    });
  }

  closeBatchDetails() {
    this.batchDetailsModal?.classList.remove('active');
  }

  async openBatchDetails(batchId) {
    try {
      const history = await PromedApi.get(`/inventory/batches/${batchId}/history`);
      this.renderBatchDetails(history);
      this.batchDetailsModal.classList.add('active');
    } catch (error) {
      this.showStatus(error.message, true, 'expiryStatus');
    }
  }

  renderBatchDetails(history) {
    const batch = history.batch;
    const transactions = history.transactions.length
      ? history.transactions.map(item => `
          <tr>
            <td>${this.escapeHtml(new Date(item.created_at).toLocaleString())}</td>
            <td>${this.escapeHtml(item.kind)}</td>
            <td>${item.quantity_delta > 0 ? '+' : ''}${item.quantity_delta}</td>
            <td>${item.previous_quantity.toLocaleString()} → ${item.updated_quantity.toLocaleString()}</td>
            <td>${this.escapeHtml(item.reason || '—')}</td>
          </tr>
        `).join('')
      : '<tr><td colspan="5" class="empty-state">No stock transactions for this batch.</td></tr>';
    const statusEvents = history.status_events.length
      ? history.status_events.map(event => `
          <tr>
            <td>${this.escapeHtml(new Date(event.created_at).toLocaleString())}</td>
            <td>${this.escapeHtml(event.previous_status)} → ${this.escapeHtml(event.updated_status)}</td>
            <td>${this.escapeHtml(event.reason)}</td>
          </tr>
        `).join('')
      : '<tr><td colspan="3" class="empty-state">No batch status changes have been recorded.</td></tr>';
    const statusOptions = ['active', 'quarantined', 'damaged']
      .map(status => `<option value="${status}" ${batch.status === status ? 'selected' : ''}>${status}</option>`)
      .join('');

    this.batchDetailsContent.innerHTML = `
      <div class="modal-heading">
        <div>
          <h2>${this.escapeHtml(batch.product_name)} · ${this.escapeHtml(batch.batch_number)}</h2>
          <p class="section-description">${this.escapeHtml(batch.category_name)} · ${this.escapeHtml(batch.location_code)} · ${this.escapeHtml(batch.expiry_category.replace(/_/g, ' '))}</p>
        </div>
        <button class="modal-close" type="button" data-close-batch-modal aria-label="Close batch details">×</button>
      </div>
      <div class="form-row">
        <p>Manufactured: <strong>${this.escapeHtml(batch.manufacturing_date || '—')}</strong></p>
        <p>Expires: <strong>${this.escapeHtml(batch.expiry_date)}</strong></p>
        <p>Purchase date: <strong>${this.escapeHtml(batch.purchase_date)}</strong></p>
        <p>Supplier: <strong>${this.escapeHtml(batch.supplier_name || '—')}</strong></p>
        <p>On hand: <strong>${batch.quantity.toLocaleString()}</strong></p>
        <p>Sellable: <strong>${batch.available_quantity.toLocaleString()}</strong></p>
        <p>Received: <strong>${batch.received_quantity.toLocaleString()}</strong></p>
        <p>Purchase price: <strong>${batch.purchase_price === null ? '—' : this.formatMoney(batch.purchase_price, this.salesConfig?.currency_code)}</strong></p>
        <p>Unit cost: <strong>${batch.unit_cost === null ? '—' : this.formatMoney(batch.unit_cost, this.salesConfig?.currency_code)}</strong></p>
        <p>Supplier reference: <strong>${this.escapeHtml(batch.supplier_reference || '—')}</strong></p>
        <p>Supplier contact: <strong>${this.escapeHtml(batch.supplier_contact || '—')}</strong></p>
        <p>Supplier address: <strong>${this.escapeHtml(batch.supplier_address || '—')}</strong></p>
      </div>
      <form id="batchStatusForm" class="stacked-form">
        <div class="form-row">
          <label>Batch status<select name="status" required>${statusOptions}</select></label>
          <label>Reason for status change<input name="reason" maxlength="240" required placeholder="Required for traceability"></label>
        </div>
        <button class="btn btn-secondary btn-sm" type="submit">Update status</button>
        <p id="batchStatusFeedback" class="form-status" role="status" aria-live="polite"></p>
      </form>
      <h3 class="section-subtitle">Batch stock transactions</h3>
      <div class="table-responsive"><table class="promed-table"><thead><tr><th>Date</th><th>Type</th><th>Change</th><th>Previous → updated</th><th>Reason</th></tr></thead><tbody>${transactions}</tbody></table></div>
      <h3 class="section-subtitle">Status history</h3>
      <div class="table-responsive"><table class="promed-table"><thead><tr><th>Date</th><th>Status change</th><th>Reason</th></tr></thead><tbody>${statusEvents}</tbody></table></div>
    `;

    this.batchDetailsContent.querySelectorAll('[data-close-batch-modal]').forEach(button => {
      button.addEventListener('click', () => this.closeBatchDetails());
    });
    this.batchDetailsContent.querySelector('#batchStatusForm').addEventListener('submit', async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const fields = new FormData(form);
      try {
        await PromedApi.patch(`/inventory/batches/${batch.id}/status`, {
          status: fields.get('status'),
          reason: fields.get('reason')
        });
        this.showStatus('Batch status updated.', false, 'batchStatusFeedback');
        await this.refreshAll();
        await this.openBatchDetails(batch.id);
      } catch (error) {
        this.showStatus(error.message, true, 'batchStatusFeedback');
      }
    });
  }

  async refreshAll() {
    const results = await Promise.allSettled([
      this.dashboard.refresh(),
      this.loadInventory(),
      this.loadLowStock(),
      this.loadExpiry(),
      this.loadSales()
    ]);
    results.filter(result => result.status === 'rejected')
      .forEach(result => this.showStatus(result.reason.message, true));
  }

  openExpiryCategory(category) {
    this.nav.navigateTo('expiry');
    const filter = document.getElementById('batchExpiryCategoryFilter');
    if (filter) filter.value = category;
    this.loadExpiry().catch(error => this.showStatus(error.message, true, 'expiryStatus'));
  }

  async searchProducts(query) {
    if (!query) return;
    const boxMatch = query.match(/^box\s+([a-z0-9]+)$/i);
    const products = boxMatch
      ? await PromedApi.get(`/products?location_code=${encodeURIComponent(boxMatch[1])}`)
      : await PromedApi.get(`/products?q=${encodeURIComponent(query)}`);
    this.dashboard.renderSearchResults(products, query);
  }

  async searchByLocation(code) {
    const products = await PromedApi.get(`/products?location_code=${encodeURIComponent(code)}`);
    this.dashboard.renderSearchResults(products, `Box ${code}`);
    this.dashboard.liveSearchResults.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  renderInventory(products) {
    const tableBody = document.getElementById('inventoryTableBody');
    if (!products.length) {
      tableBody.innerHTML = '<tr><td colspan="10" class="empty-state">No products yet. Register a product to get started.</td></tr>';
      return;
    }

    tableBody.innerHTML = products.map(product => {
      const activeBatches = product.batches.filter(batch =>
        batch.quantity > 0 && batch.status === 'active' && batch.expiry_category !== 'expired'
      );
      const nearestExpiry = activeBatches.map(batch => batch.expiry_date).sort()[0] || '—';
      const locations = product.location_quantities.length
        ? product.location_quantities.map(item =>
          `${this.escapeHtml(item.location_code)}: ${item.quantity.toLocaleString()}`
        ).join(', ')
        : '—';
      const isLow = product.min_threshold > 0 && product.available_stock_quantity <= product.min_threshold;
      const hasSellableStock = product.available_stock_quantity > 0;
      return `
        <tr>
          <td><strong>${this.escapeHtml(product.name)}</strong><div class="subtle-text">${this.escapeHtml(product.generic_name || '')}</div></td>
          <td class="text-mono">${this.escapeHtml(product.barcode || '—')}</td>
          <td>${this.escapeHtml(product.category_name)}</td>
          <td>${locations}</td>
          <td><strong>${product.stock_quantity.toLocaleString()}</strong> on hand<div class="subtle-text">${product.available_stock_quantity.toLocaleString()} sellable · ${product.expired_stock_quantity.toLocaleString()} expired</div></td>
          <td>${this.formatMoney(product.unit_price, this.salesConfig?.currency_code)}</td>
          <td>${this.escapeHtml(nearestExpiry)}${activeBatches.length > 1 ? `<div class="subtle-text">${activeBatches.length} batches</div>` : ''}</td>
          <td>
            <form class="threshold-update-form" data-product-id="${product.id}">
              <input name="min_threshold" type="number" min="0" max="1000000" step="1" value="${product.min_threshold}" aria-label="Minimum stock for ${this.escapeHtml(product.name)}">
              <button class="btn btn-secondary btn-sm" type="submit">Save</button>
            </form>
          </td>
          <td><span class="badge-status ${!hasSellableStock || isLow ? 'badge-status-low-stock' : 'badge-status-in-stock'}">${!hasSellableStock ? 'Unavailable' : isLow ? 'Low stock' : 'Available'}</span></td>
          <td><button class="btn btn-secondary btn-sm" type="button" data-product-id="${product.id}">View</button></td>
        </tr>
      `;
    }).join('');

    tableBody.querySelectorAll('[data-product-id]').forEach(button => {
      button.addEventListener('click', () => this.openProduct(Number(button.dataset.productId)));
    });
    tableBody.querySelectorAll('.threshold-update-form').forEach(form => {
      form.addEventListener('submit', async event => {
        event.preventDefault();
        const fields = new FormData(form);
        try {
          await PromedApi.patch(`/products/${form.dataset.productId}`, {
            min_threshold: Number(fields.get('min_threshold'))
          });
          this.showStatus('Minimum stock level updated.', false, 'inventoryStatus');
          await this.refreshAll();
        } catch (error) {
          this.showStatus(error.message, true, 'inventoryStatus');
        }
      });
    });
  }

  renderTransactions(transactions) {
    const tableBody = document.getElementById('inventoryTransactionTableBody');
    if (!transactions.length) {
      tableBody.innerHTML = '<tr><td colspan="8" class="empty-state">No stock transactions have been recorded.</td></tr>';
      return;
    }

    const labels = { receipt: 'Received', adjustment: 'Adjusted', sale: 'Sold' };
    tableBody.innerHTML = transactions.map(item => `
      <tr>
        <td>${this.escapeHtml(new Date(item.created_at).toLocaleString())}</td>
        <td><strong>${this.escapeHtml(item.product_name)}</strong><div class="subtle-text">${this.escapeHtml(item.batch_number)}</div></td>
        <td>${this.escapeHtml(item.location_code)}</td>
        <td>${labels[item.kind] || this.escapeHtml(item.kind)}</td>
        <td>${item.quantity_delta > 0 ? '+' : ''}${item.quantity_delta}</td>
        <td>${item.previous_quantity.toLocaleString()}</td>
        <td>${item.updated_quantity.toLocaleString()}</td>
        <td>${this.escapeHtml(item.reason || '—')}</td>
      </tr>
    `).join('');
  }

  setupSalesWorkflows() {
    const search = document.getElementById('posProductSearch');
    search?.addEventListener('input', () => {
      clearTimeout(this.posSearchTimer);
      this.posSearchTimer = setTimeout(() => {
        this.searchPosProducts(search.value).catch(error => this.showStatus(error.message, true, 'salesStatus'));
      }, 250);
    });
    search?.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        clearTimeout(this.posSearchTimer);
        this.searchPosProducts(search.value).catch(error => this.showStatus(error.message, true, 'salesStatus'));
      }
    });
    document.getElementById('posSearchResults')?.addEventListener('click', event => {
      const button = event.target.closest('[data-pos-add]');
      if (!button) return;
      const product = this.posSearchResults?.find(item => item.id === Number(button.dataset.posAdd));
      if (!product) return;
      this.addToPosCart(product);
    });
    document.getElementById('posCartBody')?.addEventListener('change', event => {
      const input = event.target.closest('[data-cart-quantity]');
      if (!input) return;
      const item = this.posCart.find(cartItem => cartItem.product.id === Number(input.dataset.cartQuantity));
      if (!item) return;
      const quantity = Number(input.value);
      if (!Number.isInteger(quantity) || quantity < 1) {
        this.posCart = this.posCart.filter(cartItem => cartItem !== item);
      } else {
        item.quantity = quantity;
      }
      this.renderPosCart();
    });
    document.getElementById('posCartBody')?.addEventListener('click', event => {
      const button = event.target.closest('[data-cart-remove]');
      if (!button) return;
      this.posCart = this.posCart.filter(item => item.product.id !== Number(button.dataset.cartRemove));
      this.renderPosCart();
    });
    document.getElementById('checkoutForm')?.addEventListener('input', event => {
      if (event.target.name === 'payment_amount') event.target.dataset.autoAmount = 'false';
      if (event.target.name === 'discount_amount') this.renderPosCart();
    });
    document.getElementById('checkoutForm')?.addEventListener('submit', event => {
      event.preventDefault();
      this.submitCheckout(event.currentTarget).catch(error => this.showStatus(error.message, true, 'salesStatus'));
    });
    document.getElementById('refreshSalesBtn')?.addEventListener('click', () => {
      this.loadSales().catch(error => this.showStatus(error.message, true, 'salesStatus'));
    });
    document.getElementById('salesHistoryForm')?.addEventListener('submit', event => {
      event.preventDefault();
      this.loadSalesHistory(new FormData(event.currentTarget))
        .catch(error => this.showStatus(error.message, true, 'salesStatus'));
    });
    document.getElementById('salesHistoryBody')?.addEventListener('click', event => {
      const button = event.target.closest('[data-sale-action]');
      if (!button) return;
      const saleId = Number(button.dataset.saleId);
      if (button.dataset.saleAction === 'invoice') {
        this.loadInvoice(saleId).catch(error => this.showStatus(error.message, true, 'salesStatus'));
      } else if (button.dataset.saleAction === 'return') {
        this.openReturnForm(saleId).catch(error => this.showStatus(error.message, true, 'salesStatus'));
      }
    });
    document.getElementById('returnForm')?.addEventListener('submit', event => {
      event.preventDefault();
      this.submitReturn(event.currentTarget).catch(error => this.showStatus(error.message, true, 'salesStatus'));
    });
    document.getElementById('printInvoiceBtn')?.addEventListener('click', () => this.printInvoice());
    document.getElementById('salesConfigForm')?.addEventListener('submit', event => {
      event.preventDefault();
      this.saveSalesConfig(event.currentTarget).catch(error => this.showStatus(error.message, true, 'salesConfigStatus'));
    });
  }

  setupOrderWorkflows() {
    document.getElementById('addOrderItemBtn')?.addEventListener('click', () => {
      try {
        this.addOrderItem();
      } catch (error) {
        this.showStatus(error.message, true, 'ordersStatus');
      }
    });
    document.getElementById('createOrderForm')?.addEventListener('submit', event => {
      event.preventDefault();
      this.submitOrder(event.currentTarget).catch(error => this.showStatus(error.message, true, 'ordersStatus'));
    });
    document.getElementById('orderItemsBody')?.addEventListener('click', event => {
      const button = event.target.closest('[data-order-item-remove]');
      if (!button) return;
      this.orderItems = this.orderItems.filter(item => item.product.id !== Number(button.dataset.orderItemRemove));
      this.renderOrderItems();
    });
    document.getElementById('refreshOrdersBtn')?.addEventListener('click', () => {
      this.loadOrders().catch(error => this.showStatus(error.message, true, 'ordersStatus'));
    });
    document.getElementById('ordersTableBody')?.addEventListener('click', event => {
      const detailsButton = event.target.closest('[data-order-details]');
      if (detailsButton) {
        this.loadOrderDetails(Number(detailsButton.dataset.orderDetails))
          .catch(error => this.showStatus(error.message, true, 'ordersStatus'));
        return;
      }
      const statusButton = event.target.closest('[data-order-status-save]');
      if (statusButton) {
        const row = statusButton.closest('[data-order-row]');
        const select = row?.querySelector('[data-next-order-status]');
        if (select?.value) {
          const operatorReference = row.querySelector('[data-order-operator]')?.value || null;
          this.updateOrderStatus(Number(row.dataset.orderRow), select.value, operatorReference)
            .catch(error => this.showStatus(error.message, true, 'ordersStatus'));
        }
        return;
      }
      const prescriptionButton = event.target.closest('[data-prescription-save]');
      if (prescriptionButton) {
        const row = prescriptionButton.closest('[data-order-row]');
        this.savePrescriptionVerification(row).catch(error => this.showStatus(error.message, true, 'ordersStatus'));
      }
    });
  }

  async loadSalesConfig() {
    const config = await PromedApi.get('/sales/config');
    this.salesConfig = config;
    const form = document.getElementById('salesConfigForm');
    if (form && config.configured) {
      form.elements.store_name.value = config.store_name || '';
      form.elements.store_phone.value = config.store_phone || '';
      form.elements.store_address.value = config.store_address || '';
      form.elements.tax_rate_percent.value = config.tax_rate_percent;
      form.elements.currency_code.value = config.currency_code || '';
    }
    this.renderPosCart();
    if (this.dashboard) await this.dashboard.refresh();
  }

  async saveSalesConfig(form) {
    const fields = new FormData(form);
    const config = await PromedApi.put('/sales/config', {
      store_name: fields.get('store_name'),
      store_phone: fields.get('store_phone'),
      store_address: fields.get('store_address') || null,
      tax_rate_percent: Number(fields.get('tax_rate_percent')),
      currency_code: fields.get('currency_code')
    });
    this.salesConfig = config;
    this.showStatus('Store and invoice configuration saved.', false, 'salesConfigStatus');
    this.renderPosCart();
    if (this.products.length) this.renderInventory(this.products);
    if (this.dashboard) await this.dashboard.refresh();
  }

  async loadSales() {
    const [summary, history, returns] = await Promise.all([
      PromedApi.get('/sales/summary'),
      PromedApi.get('/sales/history?limit=50'),
      PromedApi.get('/sales/returns?limit=50')
    ]);
    this.renderSalesSummary(summary);
    this.renderSalesHistory(history);
    this.renderReturnHistory(returns);
  }

  async loadSalesHistory(formData = null) {
    const query = new URLSearchParams();
    if (formData) {
      const invoice = String(formData.get('invoice_number') || '').trim();
      const phone = String(formData.get('customer_phone') || '').trim();
      if (invoice) query.set('invoice_number', invoice);
      if (phone) query.set('customer_phone', phone);
    }
    const history = await PromedApi.get(`/sales/history${query.size ? `?${query.toString()}` : ''}`);
    this.renderSalesHistory(history);
  }

  renderSalesSummary(summary) {
    const money = value => this.formatMoney(value, this.salesConfig?.currency_code);
    document.getElementById('salesTodayRevenue').textContent = money(summary.today_revenue);
    document.getElementById('salesTodayTransactions').textContent = summary.today_transactions.toLocaleString();
    document.getElementById('salesWeekRevenue').textContent = money(summary.week_revenue);
    document.getElementById('salesMonthRevenue').textContent = money(summary.month_revenue);
    const bestSellers = document.getElementById('salesBestSellers');
    bestSellers.innerHTML = summary.best_sellers.length
      ? summary.best_sellers.map(item => `<tr><td>${this.escapeHtml(item.product_name)}</td><td>${item.units_sold.toLocaleString()}</td></tr>`).join('')
      : '<tr><td colspan="2" class="empty-state">No sales recorded.</td></tr>';
    const dailyRevenue = document.getElementById('salesDailyRevenue');
    dailyRevenue.innerHTML = summary.daily_revenue.map(item =>
      `<tr><td>${this.escapeHtml(item.day)}</td><td>${money(item.revenue)}</td></tr>`
    ).join('');
  }

  renderSalesHistory(sales) {
    const body = document.getElementById('salesHistoryBody');
    body.innerHTML = sales.length
      ? sales.map(sale => `
          <tr>
            <td><strong>${this.escapeHtml(sale.invoice_number)}</strong></td>
            <td>${this.escapeHtml(new Date(sale.created_at).toLocaleString())}</td>
            <td>${this.escapeHtml(sale.customer_name || '—')}${sale.customer_phone ? `<div class="subtle-text">${this.escapeHtml(sale.customer_phone)}</div>` : ''}</td>
            <td>${sale.item_count}</td>
            <td>${this.formatMoney(sale.total_amount, sale.currency_code)}</td>
            <td>${this.escapeHtml(sale.payment_method || 'Recorded sale')}</td>
            <td class="table-actions"><button class="btn btn-secondary btn-sm" type="button" data-sale-action="invoice" data-sale-id="${sale.sale_id}">Invoice</button><button class="btn btn-secondary btn-sm" type="button" data-sale-action="return" data-sale-id="${sale.sale_id}">Return</button></td>
          </tr>
        `).join('')
      : '<tr><td colspan="7" class="empty-state">No invoices match this search.</td></tr>';
  }

  renderReturnHistory(returns) {
    const body = document.getElementById('returnsHistoryBody');
    body.innerHTML = returns.length
      ? returns.map(item => `
          <tr>
            <td><strong>${this.escapeHtml(item.return_number)}</strong></td>
            <td>${this.escapeHtml(item.invoice_number)}</td>
            <td>${this.escapeHtml(new Date(item.created_at).toLocaleString())}</td>
            <td>${item.items.map(line => `${this.escapeHtml(line.product_name)} × ${line.quantity} · ${this.escapeHtml(line.disposition)}`).join('<br>')}</td>
            <td>${this.escapeHtml(item.reason)}</td>
            <td>${this.formatMoney(item.refund_amount, this.salesConfig?.currency_code)}</td>
          </tr>
        `).join('')
      : '<tr><td colspan="6" class="empty-state">No returns recorded.</td></tr>';
  }

  async searchPosProducts(query) {
    const term = query.trim();
    const body = document.getElementById('posSearchResults');
    if (!term) {
      this.posSearchResults = [];
      body.innerHTML = '<tr><td colspan="6" class="empty-state">Search products to add them to the cart.</td></tr>';
      return;
    }
    let products = await PromedApi.get(`/products?barcode=${encodeURIComponent(term)}`);
    if (!products.length) products = await PromedApi.get(`/products?q=${encodeURIComponent(term)}`);
    this.posSearchResults = products;
    body.innerHTML = products.length
      ? products.map(product => `
          <tr>
            <td><strong>${this.escapeHtml(product.name)}</strong><div class="subtle-text">${this.escapeHtml(product.generic_name || '')}</div></td>
            <td>${this.escapeHtml(product.barcode || '—')}</td>
            <td>${product.available_stock_quantity.toLocaleString()}</td>
            <td>${this.formatMoney(product.unit_price, this.salesConfig?.currency_code)}</td>
            <td>${product.requires_prescription ? '<span class="badge-status badge-status-low-stock">Prescription</span>' : 'Not required'}</td>
            <td><button class="btn btn-secondary btn-sm" type="button" data-pos-add="${product.id}" ${product.available_stock_quantity < 1 ? 'disabled' : ''}>Add</button></td>
          </tr>
        `).join('')
      : '<tr><td colspan="6" class="empty-state">No matching products found.</td></tr>';
  }

  addToPosCart(product) {
    const existing = this.posCart.find(item => item.product.id === product.id);
    if (existing) existing.quantity += 1;
    else this.posCart.push({ product, quantity: 1 });
    this.renderPosCart();
  }

  renderPosCart() {
    const body = document.getElementById('posCartBody');
    if (!body) return;
    body.innerHTML = this.posCart.length
      ? this.posCart.map(item => `
          <tr>
            <td><strong>${this.escapeHtml(item.product.name)}</strong>${item.product.requires_prescription ? '<div class="subtle-text">Prescription required</div>' : ''}</td>
            <td><input data-cart-quantity="${item.product.id}" type="number" min="1" step="1" value="${item.quantity}" aria-label="Quantity for ${this.escapeHtml(item.product.name)}"></td>
            <td>${this.formatMoney(item.product.unit_price, this.salesConfig?.currency_code)}</td>
            <td>${this.formatMoney(Number(item.product.unit_price) * item.quantity, this.salesConfig?.currency_code)}</td>
            <td><button class="btn btn-secondary btn-sm" type="button" data-cart-remove="${item.product.id}">Remove</button></td>
          </tr>
        `).join('')
      : '<tr><td colspan="5" class="empty-state">Cart is empty.</td></tr>';
    const subtotalCents = this.posCart.reduce(
      (total, item) => total + Math.round(Number(item.product.unit_price) * 100) * item.quantity,
      0
    );
    const checkout = document.getElementById('checkoutForm');
    const discountCents = Math.min(
      Math.round(Number(checkout?.elements.discount_amount.value || 0) * 100),
      subtotalCents
    );
    const taxRate = this.salesConfig?.configured ? Number(this.salesConfig.tax_rate_percent) : null;
    const taxCents = taxRate === null ? null : Math.round((subtotalCents - discountCents) * taxRate / 100);
    const totalCents = taxCents === null ? null : Math.max(0, subtotalCents - discountCents + taxCents);
    document.getElementById('posSubtotal').textContent = this.formatMoney(subtotalCents / 100, this.salesConfig?.currency_code);
    document.getElementById('posDiscount').textContent = this.formatMoney(discountCents / 100, this.salesConfig?.currency_code);
    document.getElementById('posTax').textContent = taxCents === null
      ? 'Configure store and tax settings'
      : `${this.formatMoney(taxCents / 100, this.salesConfig.currency_code)} (${taxRate}%)`;
    document.getElementById('posTotal').textContent = totalCents === null
      ? 'Configure store settings'
      : this.formatMoney(totalCents / 100, this.salesConfig.currency_code);
    const paymentAmount = checkout?.elements.payment_amount;
    if (paymentAmount && totalCents !== null && paymentAmount.dataset.autoAmount !== 'false') {
      paymentAmount.value = (totalCents / 100).toFixed(2);
      paymentAmount.dataset.autoAmount = 'true';
    }
  }

  async submitCheckout(form) {
    if (!this.salesConfig?.configured) {
      throw new Error('Configure store name, phone, currency, and tax rate in Settings before checkout.');
    }
    if (!this.posCart.length) throw new Error('Add at least one product to the billing cart.');
    const fields = new FormData(form);
    const payload = {
      items: this.posCart.map(item => ({ product_id: item.product.id, quantity: item.quantity })),
      discount_amount: Number(fields.get('discount_amount') || 0),
      discount_authorized_by: fields.get('discount_authorized_by') || null,
      discount_reason: fields.get('discount_reason') || null,
      prescription_reference: fields.get('prescription_reference') || null,
      pharmacist_reference: fields.get('pharmacist_reference') || null,
      customer_name: fields.get('customer_name') || null,
      customer_phone: fields.get('customer_phone') || null,
      operator_reference: fields.get('operator_reference'),
      payment_method: fields.get('payment_method'),
      payment_amount: Number(fields.get('payment_amount')),
      payment_reference: fields.get('payment_reference') || null,
      idempotency_key: this.newIdempotencyKey('checkout')
    };
    const invoice = await PromedApi.post('/sales/checkout', payload);
    this.posCart = [];
    form.reset();
    form.elements.payment_amount.dataset.autoAmount = 'true';
    this.renderPosCart();
    document.getElementById('posProductSearch').value = '';
    this.posSearchResults = [];
    document.getElementById('posSearchResults').innerHTML =
      '<tr><td colspan="6" class="empty-state">Search products to add them to the cart.</td></tr>';
    await this.refreshAll();
    this.renderInvoice(invoice);
    this.showStatus(`Checkout completed. Invoice ${invoice.invoice_number} was recorded.`, false, 'salesStatus');
  }

  async loadInvoice(saleId) {
    const invoice = await PromedApi.get(`/sales/${saleId}/invoice`);
    this.renderInvoice(invoice);
  }

  renderInvoice(invoice) {
    const panel = document.getElementById('invoicePreviewPanel');
    const currency = invoice.currency_code || '';
    document.getElementById('invoicePreviewMeta').textContent =
      `${invoice.invoice_number} · ${new Date(invoice.created_at).toLocaleString()}`;
    document.getElementById('invoicePdfLink').href =
      `${window.PROMED_API_BASE_URL || 'http://127.0.0.1:8000/api'}/sales/${invoice.sale_id}/invoice.pdf`;
    document.getElementById('invoicePreviewContent').innerHTML = `
      <div class="invoice-print-content">
        <h3>${this.escapeHtml(invoice.store_name || 'Store name not configured')}</h3>
        <p>${this.escapeHtml(invoice.store_phone || '')} ${this.escapeHtml(invoice.store_address || '')}</p>
        <p><strong>Customer:</strong> ${this.escapeHtml(invoice.customer_name || '—')} · ${this.escapeHtml(invoice.customer_phone || '—')}</p>
          <p><strong>Operator:</strong> ${this.escapeHtml(invoice.operator_reference || '—')} · <strong>Pharmacist:</strong> ${this.escapeHtml(invoice.pharmacist_reference || '—')}</p>
          <p><strong>Prescription reference:</strong> ${this.escapeHtml(invoice.prescription_reference || '—')} · <strong>Payment:</strong> ${this.escapeHtml(invoice.payment?.method || 'Not recorded')}${invoice.payment?.reference ? ` · ${this.escapeHtml(invoice.payment.reference)}` : ''}</p>
          ${invoice.discount_authorized_by ? `<p><strong>Discount authorized by:</strong> ${this.escapeHtml(invoice.discount_authorized_by)} · ${this.escapeHtml(invoice.discount_reason || '')}</p>` : ''}
        <div class="table-responsive"><table class="promed-table"><thead><tr><th>Product / batch</th><th>Qty</th><th>Unit price</th><th>Discount</th><th>Tax</th><th>Total</th></tr></thead><tbody>
          ${invoice.items.map(item => `<tr><td>${this.escapeHtml(item.product_name)}<div class="subtle-text">${this.escapeHtml(item.batch_number)}</div></td><td>${item.quantity}</td><td>${this.formatMoney(item.unit_price, currency)}</td><td>${this.formatMoney(item.discount_amount, currency)}</td><td>${this.formatMoney(item.tax_amount, currency)}</td><td>${this.formatMoney(item.line_total, currency)}</td></tr>`).join('')}
        </tbody></table></div>
        <div class="pos-totals"><div><span>Subtotal</span><strong>${this.formatMoney(invoice.subtotal_amount, currency)}</strong></div><div><span>Discount</span><strong>${this.formatMoney(invoice.discount_amount, currency)}</strong></div><div><span>Configured tax (${Number(invoice.tax_rate_percent).toFixed(2)}%)</span><strong>${this.formatMoney(invoice.tax_amount, currency)}</strong></div><div class="pos-grand-total"><span>Total</span><strong>${this.formatMoney(invoice.total_amount, currency)}</strong></div></div>
      </div>
    `;
    panel.hidden = false;
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  printInvoice() {
    const content = document.querySelector('#invoicePreviewContent .invoice-print-content');
    if (!content) return;
    const printWindow = window.open('', '_blank');
    if (!printWindow) {
      this.showStatus('Allow pop-ups to print the invoice, or download the PDF.', true, 'salesStatus');
      return;
    }
    printWindow.opener = null;
    printWindow.document.write(`<!doctype html><html><head><title>PROMED invoice</title><style>body{font:14px Arial,sans-serif;margin:32px;color:#152238}table{width:100%;border-collapse:collapse;margin:20px 0}th,td{text-align:left;padding:8px;border:1px solid #ccd4df}.pos-totals{max-width:380px;margin-left:auto}.pos-totals div{display:flex;justify-content:space-between;padding:4px}</style></head><body>${content.innerHTML}</body></html>`);
    printWindow.document.close();
    printWindow.focus();
    setTimeout(() => {
      printWindow.print();
      printWindow.close();
    }, 250);
  }

  async openReturnForm(saleId) {
    const invoice = await PromedApi.get(`/sales/${saleId}/invoice`);
    const form = document.getElementById('returnForm');
    form.elements.sale_id.value = saleId;
    document.getElementById('returnItems').innerHTML = invoice.items.map(item => {
      const remaining = item.quantity - item.returned_quantity;
      return `
        <div class="return-item-row">
          <strong>${this.escapeHtml(item.product_name)} · batch ${this.escapeHtml(item.batch_number)}</strong>
          <span>Sold ${item.quantity}; already returned ${item.returned_quantity}; remaining ${remaining}</span>
          <div class="form-row">
            <label>Return quantity<input data-return-quantity="${item.sale_item_id}" type="number" min="0" max="${remaining}" step="1" value="0"></label>
            <label><span><input data-return-restock="${item.sale_item_id}" type="checkbox"> Restock after inspection</span><input data-return-inspector="${item.sale_item_id}" maxlength="80" placeholder="Inspector reference (required to restock)" aria-label="Inspector reference"></label>
          </div>
        </div>`;
    }).join('');
    document.getElementById('returnPanel').hidden = false;
    document.getElementById('returnPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async submitReturn(form) {
    const fields = new FormData(form);
    const items = Array.from(form.querySelectorAll('[data-return-quantity]'))
      .map(input => {
        const saleItemId = input.dataset.returnQuantity;
        const restock = form.querySelector(`[data-return-restock="${saleItemId}"]`).checked;
        const item = { sale_item_id: Number(saleItemId), quantity: Number(input.value), restock };
        const inspector = form.querySelector(`[data-return-inspector="${saleItemId}"]`).value.trim();
        if (restock && inspector) item.restock_verified_by = inspector;
        return item;
      })
      .filter(item => item.quantity > 0);
    if (!items.length) throw new Error('Enter a return quantity for at least one invoice item.');
    const result = await PromedApi.post(`/sales/${fields.get('sale_id')}/returns`, {
      items,
      reason: fields.get('reason'),
      refund_method: fields.get('refund_method'),
      refund_reference: fields.get('refund_reference') || null,
      operator_reference: fields.get('operator_reference'),
      idempotency_key: this.newIdempotencyKey('return')
    });
    this.showStatus(`Return ${result.return_number} recorded for ${this.formatMoney(result.refund_amount, this.salesConfig?.currency_code)}.`, false, 'salesStatus');
    form.reset();
    document.getElementById('returnPanel').hidden = true;
    await this.refreshAll();
  }

  async loadOrders() {
    const orders = await PromedApi.get('/orders/workflow?limit=100');
    this.renderOrders(orders);
  }

  populateOrderProductOptions() {
    const select = document.getElementById('orderProductSelect');
    if (!select) return;
    select.innerHTML = `<option value="">Select a product</option>${this.products.map(product =>
      `<option value="${product.id}">${this.escapeHtml(product.name)}${product.requires_prescription ? ' · prescription required' : ''}</option>`
    ).join('')}`;
  }

  addOrderItem() {
    const form = document.getElementById('createOrderForm');
    const productId = Number(form.elements.product_id.value);
    const quantity = Number(form.elements.quantity.value);
    const product = this.products.find(item => item.id === productId);
    if (!product) throw new Error('Select a product to add to the order.');
    if (!Number.isInteger(quantity) || quantity < 1) throw new Error('Order quantity must be a positive whole number.');
    const existing = this.orderItems.find(item => item.product.id === productId);
    if (existing) existing.quantity += quantity;
    else this.orderItems.push({ product, quantity });
    this.renderOrderItems();
    form.elements.product_id.value = '';
    form.elements.quantity.value = '1';
  }

  renderOrderItems() {
    const body = document.getElementById('orderItemsBody');
    if (!body) return;
    body.innerHTML = this.orderItems.length
      ? this.orderItems.map(item => `<tr><td>${this.escapeHtml(item.product.name)}${item.product.requires_prescription ? ' · prescription required' : ''}</td><td>${item.quantity}</td><td><button class="btn btn-secondary btn-sm" type="button" data-order-item-remove="${item.product.id}">Remove</button></td></tr>`).join('')
      : '<tr><td colspan="3" class="empty-state">No products added.</td></tr>';
  }

  async submitOrder(form) {
    const fields = new FormData(form);
    if (!this.orderItems.length) throw new Error('Add at least one product to the order.');
    const order = await PromedApi.post('/orders/workflow', {
      items: this.orderItems.map(item => ({ product_id: item.product.id, quantity: item.quantity })),
      customer_name: fields.get('customer_name') || null,
      customer_phone: fields.get('customer_phone') || null,
      fulfillment_method: fields.get('fulfillment_method'),
      delivery_address: fields.get('delivery_address') || null,
      notes: fields.get('notes') || null,
      operator_reference: fields.get('operator_reference') || null,
      prescription_reference: fields.get('prescription_reference') || null
    });
    this.orderItems = [];
    this.renderOrderItems();
    form.reset();
    this.showStatus(`Order ${order.order_number} created. No inventory was reserved or deducted.`, false, 'ordersStatus');
    await this.loadOrders();
  }

  renderOrders(orders) {
    const body = document.getElementById('ordersTableBody');
    body.innerHTML = orders.length
      ? orders.map(order => {
          const transitions = {
            RECEIVED: ['PHARMACIST_REVIEW', 'CANCELLED'],
            PHARMACIST_REVIEW: ['ACCEPTED', 'REJECTED', 'CANCELLED'],
            ACCEPTED: ['PREPARING', 'CANCELLED'],
            PREPARING: order.fulfillment_method === 'pickup'
              ? ['READY_FOR_PICKUP', 'CANCELLED']
              : ['OUT_FOR_DELIVERY', 'CANCELLED'],
            READY_FOR_PICKUP: ['COMPLETED', 'CANCELLED'],
            OUT_FOR_DELIVERY: ['COMPLETED'],
            COMPLETED: [],
            REJECTED: [],
            CANCELLED: []
          }[order.status] || [];
          const roleTransitions = this.staffRole === 'operator'
            ? ['PREPARING', 'READY_FOR_PICKUP', 'OUT_FOR_DELIVERY', 'COMPLETED', 'CANCELLED']
            : this.staffRole === 'pharmacist'
              ? ['PHARMACIST_REVIEW', 'ACCEPTED', 'REJECTED', 'CANCELLED']
              : null;
          const visibleTransitions = roleTransitions
            ? transitions.filter(status => roleTransitions.includes(status))
            : transitions;
          const prescription = order.prescription_status === 'not_required'
            ? 'Not required'
            : `${order.prescription_status}${order.prescription_reference ? ` · ${order.prescription_reference}` : ''}`;
          return `
            <tr data-order-row="${order.id}">
              <td><strong>${this.escapeHtml(order.order_number)}</strong><div class="subtle-text">${this.escapeHtml(order.created_at)}</div></td>
              <td>${this.escapeHtml(order.customer_name || '—')}<div class="subtle-text">${this.escapeHtml(order.customer_phone || '')}</div></td>
              <td>${order.items.map(item => `${this.escapeHtml(item.product_name)} × ${item.quantity}${item.requires_prescription ? ' · Rx' : ''}`).join('<br>')}</td>
              <td>${this.formatMoney(order.total_amount)}</td>
              <td>${this.escapeHtml(order.fulfillment_method)}${order.fulfillment_method === 'delivery' ? `<div class="subtle-text">${this.escapeHtml(order.delivery_address || '')}</div>` : ''}</td>
              <td>${this.escapeHtml(prescription)}</td>
              <td>${this.escapeHtml(order.status)}</td>
              <td class="order-action-cell">
                <button class="btn btn-secondary btn-sm" type="button" data-order-details="${order.id}">Details</button>
                ${visibleTransitions.length ? `<div class="order-status-controls"><select data-next-order-status aria-label="Next status for ${this.escapeHtml(order.order_number)}">${visibleTransitions.map(status => `<option value="${status}">${status}</option>`).join('')}</select><input data-order-operator maxlength="80" placeholder="Operator reference" aria-label="Operator reference"><button class="btn btn-secondary btn-sm" type="button" data-order-status-save>Update</button></div>` : ''}
                ${['owner', 'pharmacist'].includes(this.staffRole) && order.prescription_status !== 'not_required' && order.status === 'PHARMACIST_REVIEW' ? `<div class="prescription-controls"><select data-prescription-status><option value="verified">Verify</option><option value="rejected">Reject</option></select><input data-pharmacist-reference maxlength="80" placeholder="Pharmacist reference" aria-label="Pharmacist reference"><input data-prescription-reference maxlength="160" value="${this.escapeHtml(order.prescription_reference || '')}" placeholder="Prescription reference" aria-label="Prescription reference"><button class="btn btn-secondary btn-sm" type="button" data-prescription-save>Record review</button></div>` : ''}
              </td>
            </tr>`;
        }).join('')
      : '<tr><td colspan="8" class="empty-state">No customer orders have been created.</td></tr>';
  }

  async updateOrderStatus(orderId, status, operatorReference) {
    await PromedApi.patch(`/orders/${orderId}/workflow`, { status, operator_reference: operatorReference });
    this.showStatus(`Order status updated to ${status}.`, false, 'ordersStatus');
    await this.loadOrders();
  }

  async savePrescriptionVerification(row) {
    if (!row) return;
    const orderId = Number(row.dataset.orderRow);
    await PromedApi.patch(`/orders/${orderId}/prescription`, {
      status: row.querySelector('[data-prescription-status]').value,
      pharmacist_reference: row.querySelector('[data-pharmacist-reference]').value,
      prescription_reference: row.querySelector('[data-prescription-reference]').value || null
    });
    this.showStatus('Prescription review was recorded by the pharmacist reference provided.', false, 'ordersStatus');
    await this.loadOrders();
  }

  async loadOrderDetails(orderId) {
    const history = await PromedApi.get(`/orders/${orderId}/workflow`);
    const order = history.order;
    document.getElementById('orderDetailsContent').innerHTML = `
      <p><strong>${this.escapeHtml(order.order_number)}</strong> · ${this.escapeHtml(order.customer_name || '—')} · ${this.escapeHtml(order.customer_phone || '—')}</p>
      <p>Total: ${this.formatMoney(order.total_amount)}</p>
      <p>${this.escapeHtml(order.fulfillment_method)}${order.delivery_address ? ` · ${this.escapeHtml(order.delivery_address)}` : ''}</p>
      <p>Notes: ${this.escapeHtml(order.notes || '—')}</p>
      <h3 class="section-subtitle">Status history</h3>
      <div class="table-responsive"><table class="promed-table"><thead><tr><th>Time</th><th>From</th><th>To</th><th>Operator</th><th>Note</th></tr></thead><tbody>${history.status_events.map(event => `<tr><td>${this.escapeHtml(event.created_at)}</td><td>${this.escapeHtml(event.previous_status || '—')}</td><td>${this.escapeHtml(event.updated_status)}</td><td>${this.escapeHtml(event.operator_reference || '—')}</td><td>${this.escapeHtml(event.note || '—')}</td></tr>`).join('')}</tbody></table></div>
      <h3 class="section-subtitle">Prescription review history</h3>
      <div class="table-responsive"><table class="promed-table"><thead><tr><th>Time</th><th>Status</th><th>Prescription reference</th><th>Pharmacist</th><th>Note</th></tr></thead><tbody>${history.prescription_events.length ? history.prescription_events.map(event => `<tr><td>${this.escapeHtml(event.created_at)}</td><td>${this.escapeHtml(event.status)}</td><td>${this.escapeHtml(event.prescription_reference || '—')}</td><td>${this.escapeHtml(event.pharmacist_reference || '—')}</td><td>${this.escapeHtml(event.note || '—')}</td></tr>`).join('') : '<tr><td colspan="5" class="empty-state">No prescription review was recorded.</td></tr>'}</tbody></table></div>
    `;
    document.getElementById('orderDetailsPanel').hidden = false;
    document.getElementById('orderDetailsPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  formatMoney(amount, currencyCode = null) {
    const value = Number(amount || 0).toFixed(2);
    return currencyCode ? `${this.escapeHtml(currencyCode)} ${value}` : value;
  }

  newIdempotencyKey(prefix) {
    const randomPart = window.crypto?.randomUUID
      ? window.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `${prefix}-${randomPart}`.slice(0, 80);
  }

  setupInventoryForms() {
    document.getElementById('createProductForm')?.addEventListener('submit', async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const fields = new FormData(form);
      try {
        await PromedApi.post('/products', {
          name: fields.get('name'),
          generic_name: fields.get('generic_name') || null,
          barcode: fields.get('barcode') || null,
          category_name: fields.get('category_name'),
          min_threshold: Number(fields.get('min_threshold')),
          unit_price: Number(fields.get('unit_price')),
          requires_prescription: fields.get('requires_prescription') === 'on',
          manufacturer: fields.get('manufacturer') || null,
          image_url: fields.get('image_url') || null,
          description: fields.get('description') || null,
          ingredients_strengths: fields.get('ingredients_strengths') || null,
          common_uses: fields.get('common_uses') || null,
          directions: fields.get('directions') || null,
          warnings: fields.get('warnings') || null,
          product_information_verified: fields.get('product_information_verified') === 'on'
        });
        form.reset();
        this.showStatus('Product created.', false, 'inventoryStatus');
        await this.refreshAll();
      } catch (error) {
        this.showStatus(error.message, true, 'inventoryStatus');
      }
    });

    document.getElementById('receiveStockForm')?.addEventListener('submit', async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const fields = new FormData(form);
      try {
        await PromedApi.post('/inventory/receipts', {
          product_id: Number(fields.get('product_id')),
          batch_number: fields.get('batch_number'),
          manufacturing_date: fields.get('manufacturing_date') || null,
          expiry_date: fields.get('expiry_date'),
          purchase_date: fields.get('purchase_date'),
          quantity: Number(fields.get('quantity')),
          location_code: fields.get('location_code'),
          supplier_id: fields.get('supplier_id') ? Number(fields.get('supplier_id')) : null,
          purchase_price: fields.get('purchase_price') ? Number(fields.get('purchase_price')) : null,
          unit_cost: fields.get('unit_cost') ? Number(fields.get('unit_cost')) : null
        });
        form.reset();
        this.showStatus('Stock receipt recorded.', false, 'inventoryStatus');
        await this.refreshAll();
      } catch (error) {
        this.showStatus(error.message, true, 'inventoryStatus');
      }
    });

    document.getElementById('supplierCreateForm')?.addEventListener('submit', async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const fields = new FormData(form);
      try {
        await PromedApi.post('/suppliers', {
          name: fields.get('name'),
          contact_details: fields.get('contact_details') || null,
          address: fields.get('address') || null,
          reference_code: fields.get('reference_code') || null
        });
        form.reset();
        this.showStatus('Supplier saved.', false, 'inventoryStatus');
        await this.loadInventory();
      } catch (error) {
        this.showStatus(error.message, true, 'inventoryStatus');
      }
    });

    document.getElementById('adjustStockForm')?.addEventListener('submit', async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const fields = new FormData(form);
      try {
        await PromedApi.post('/inventory/adjustments', {
          batch_id: Number(fields.get('batch_id')),
          quantity_delta: Number(fields.get('quantity_delta')),
          reason: fields.get('reason')
        });
        form.reset();
        this.showStatus('Stock adjustment recorded.', false, 'inventoryStatus');
        await this.refreshAll();
      } catch (error) {
        this.showStatus(error.message, true, 'inventoryStatus');
      }
    });

    document.getElementById('adjustmentProduct')?.addEventListener('change', event => {
      this.populateBatchOptions(Number(event.target.value));
    });

    document.getElementById('locationCreateForm')?.addEventListener('submit', async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const fields = new FormData(form);
      try {
        await PromedApi.post('/locations', {
          code: fields.get('code'),
          name: fields.get('name')
        });
        form.reset();
        this.showStatus('Inventory location created.', false, 'inventoryStatus');
        await this.refreshAll();
      } catch (error) {
        this.showStatus(error.message, true, 'inventoryStatus');
      }
    });

    document.getElementById('locationUpdateForm')?.addEventListener('submit', async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const fields = new FormData(form);
      try {
        await PromedApi.put(`/locations/${fields.get('location_id')}`, {
          code: fields.get('code'),
          name: fields.get('name')
        });
        this.showStatus('Inventory location updated.', false, 'inventoryStatus');
        await this.refreshAll();
      } catch (error) {
        this.showStatus(error.message, true, 'inventoryStatus');
      }
    });

    document.getElementById('inventoryLocationSelect')?.addEventListener('change', event => {
      const location = this.locations.find(item => item.id === Number(event.target.value));
      const form = event.currentTarget.form;
      if (!location || !form) return;
      form.elements.code.value = location.code;
      form.elements.name.value = location.name;
    });
  }

  populateInventoryForms() {
    const productOptions = this.products.map(product =>
      `<option value="${product.id}">${this.escapeHtml(product.name)}</option>`
    ).join('');
    ['receiptProduct', 'adjustmentProduct'].forEach(id => {
      const select = document.getElementById(id);
      if (select) select.innerHTML = `<option value="">Select a product</option>${productOptions}`;
    });

    const locationSelect = document.getElementById('receiptLocation');
    if (locationSelect) {
      locationSelect.innerHTML = `<option value="">Select a location</option>${this.locations.map(location =>
        `<option value="${this.escapeHtml(location.code)}">${this.escapeHtml(location.name)} (${this.escapeHtml(location.code)})</option>`
      ).join('')}`;
    }
    const supplierSelect = document.getElementById('receiptSupplier');
    if (supplierSelect) {
      supplierSelect.innerHTML = `<option value="">No supplier selected</option>${this.suppliers.map(supplier =>
        `<option value="${supplier.id}">${this.escapeHtml(supplier.name)}${supplier.reference_code ? ` · ${this.escapeHtml(supplier.reference_code)}` : ''}</option>`
      ).join('')}`;
    }
    const categoryFilter = document.getElementById('batchCategoryFilter');
    if (categoryFilter) {
      categoryFilter.innerHTML = `<option value="">All categories</option>${this.categories.map(category =>
        `<option value="${category.id}">${this.escapeHtml(category.name)}</option>`
      ).join('')}`;
    }
    const batchLocationFilter = document.getElementById('batchLocationFilter');
    if (batchLocationFilter) {
      batchLocationFilter.innerHTML = `<option value="">All locations</option>${this.locations.map(location =>
        `<option value="${this.escapeHtml(location.code)}">${this.escapeHtml(location.code)} · ${this.escapeHtml(location.name)}</option>`
      ).join('')}`;
    }
    const managedLocationSelect = document.getElementById('inventoryLocationSelect');
    if (managedLocationSelect) {
      managedLocationSelect.innerHTML = this.locations.map(location =>
        `<option value="${location.id}">${this.escapeHtml(location.code)} · ${this.escapeHtml(location.name)}</option>`
      ).join('');
      managedLocationSelect.dispatchEvent(new Event('change'));
    }
    this.populateBatchOptions(Number(document.getElementById('adjustmentProduct')?.value || 0));
  }

  populateBatchOptions(productId) {
    const batchSelect = document.getElementById('adjustmentBatch');
    if (!batchSelect) return;
    const product = this.products.find(item => item.id === productId);
    const batches = product ? product.batches.filter(batch => batch.quantity > 0) : [];
    batchSelect.innerHTML = `<option value="">Select a batch</option>${batches.map(batch =>
      `<option value="${batch.id}">${this.escapeHtml(batch.batch_number)} · ${this.escapeHtml(batch.location_code)} · ${batch.quantity} units</option>`
    ).join('')}`;
  }

  showStatus(message, isError = false, targetId = 'appStatus') {
    const status = document.getElementById(targetId);
    if (!status) return;
    status.textContent = message;
    status.classList.toggle('is-error', isError);
    status.classList.toggle('is-visible', Boolean(message));
  }

  escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const application = new PromedApplication();
  window.PromedApp = application;
  application.init().catch(error => application.showStatus(error.message, true));
});
