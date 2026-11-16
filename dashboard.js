/**
 * PROMED dashboard and catalog-search view.
 */
class PromedDashboard {
  constructor(app) {
    this.app = app;
    this.searchInput = document.getElementById('medicineSearchInput');
    this.searchClearBtn = document.getElementById('searchClearBtn');
    this.liveSearchResults = document.getElementById('liveSearchResults');
    this.searchResultsList = document.getElementById('searchResultsList');
    this.storageBoxesContainer = document.getElementById('storageBoxesContainer');
    this.activityFeedContainer = document.getElementById('activityFeedContainer');
    this.searchTimer = null;
    this.setupSearch();
    this.setupClock();
  }

  async refresh() {
    const data = await PromedApi.get('/dashboard');
    this.renderMetrics(data);
    this.renderLocations(data.locations);
    this.renderActivityFeed(data.recent_transactions);
    this.renderExpiryCategories(data.expiry_categories);
  }

  renderMetrics(data) {
    document.getElementById('metricRegisteredMedicines').textContent = data.product_count.toLocaleString();
    document.getElementById('metricAvailableStock').textContent = data.available_stock_units.toLocaleString();
    document.getElementById('metricTodaySales').textContent =
      `${this.app.salesConfig?.currency_code ? `${this.app.salesConfig.currency_code} ` : ''}${Number(data.today_sales_amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    document.getElementById('metricLowStock').textContent = data.low_stock_count.toLocaleString();
    document.getElementById('metricExpiringBatches').textContent = data.expiring_batch_count.toLocaleString();
  }

  renderExpiryCategories(categories) {
    const container = document.getElementById('expiryAlertsContainer');
    if (!container) return;
    const labels = {
      expired: 'Expired',
      within_30_days: 'Within 30 days',
      within_60_days: '31–60 days',
      within_90_days: '61–90 days',
      safe: 'Safe stock'
    };
    container.innerHTML = categories.map(item => `
      <button class="expiry-alert-item" type="button" data-expiry-category="${item.category}">
        <span>${labels[item.category] || this.escapeHtml(item.category)}</span>
        <strong>${item.quantity.toLocaleString()} units</strong>
        <span>${item.batch_count.toLocaleString()} batch(es)</span>
      </button>
    `).join('');
    container.querySelectorAll('[data-expiry-category]').forEach(button => {
      button.addEventListener('click', () => this.app.openExpiryCategory(button.dataset.expiryCategory));
    });
  }

  renderLocations(locations) {
    if (!this.storageBoxesContainer) return;
    if (locations.length === 0) {
      this.storageBoxesContainer.innerHTML = '<p class="empty-state">No inventory locations are configured.</p>';
      return;
    }

    this.storageBoxesContainer.innerHTML = locations.map(location => `
      <button class="storage-box-item" type="button" data-location-code="${this.escapeHtml(location.code)}">
        <div class="box-header">
          <span class="box-code-pill box-code-${this.escapeHtml(location.code.toLowerCase())}">
            <span class="led-indicator-dot"></span>${this.escapeHtml(location.code)}
          </span>
          <span class="location-badge">${location.product_count} products</span>
        </div>
        <div class="box-category-title">${this.escapeHtml(location.name)}</div>
        <div class="box-description">${location.stock_units.toLocaleString()} on hand · ${location.available_stock_units.toLocaleString()} sellable</div>
      </button>
    `).join('');

    this.storageBoxesContainer.querySelectorAll('[data-location-code]').forEach(button => {
      button.addEventListener('click', () => this.filterByLocation(button.dataset.locationCode));
    });
  }

  filterByLocation(code) {
    if (this.searchInput) this.searchInput.value = `Box ${code}`;
    this.app.searchByLocation(code).catch(error => this.app.showStatus(error.message, true));
  }

  renderActivityFeed(transactions) {
    if (!this.activityFeedContainer) return;
    if (transactions.length === 0) {
      this.activityFeedContainer.innerHTML = '<p class="empty-state">No stock transactions have been recorded.</p>';
      return;
    }

    const labels = { receipt: 'Stock received', adjustment: 'Stock adjusted', sale: 'Sale recorded' };
    this.activityFeedContainer.innerHTML = transactions.map(item => `
      <div class="activity-item">
        <div class="activity-icon-badge activity-icon-${this.escapeHtml(item.kind)}" aria-hidden="true">${item.quantity_delta > 0 ? '+' : '−'}</div>
        <div class="activity-content">
          <div class="activity-title">
            <span>${labels[item.kind] || this.escapeHtml(item.kind)}: ${this.escapeHtml(item.product_name)}</span>
            <span class="location-badge">${this.escapeHtml(item.location_code)}</span>
          </div>
          <div class="activity-detail">Batch ${this.escapeHtml(item.batch_number)} · ${item.quantity_delta > 0 ? '+' : ''}${item.quantity_delta} units · ${item.previous_quantity} → ${item.updated_quantity}${item.reason ? ` · ${this.escapeHtml(item.reason)}` : ''}</div>
          <div class="activity-time">${this.escapeHtml(new Date(item.created_at).toLocaleString())}</div>
        </div>
      </div>
    `).join('');
  }

  setupSearch() {
    if (!this.searchInput) return;

    this.searchInput.addEventListener('input', () => {
      const query = this.searchInput.value.trim();
      if (!query) {
        this.liveSearchResults.classList.remove('active');
        this.searchResultsList.replaceChildren();
        if (this.searchClearBtn) this.searchClearBtn.style.display = 'none';
        return;
      }

      if (this.searchClearBtn) this.searchClearBtn.style.display = 'block';
      clearTimeout(this.searchTimer);
      this.searchTimer = setTimeout(() => {
        this.app.searchProducts(query).catch(error => this.app.showStatus(error.message, true));
      }, 250);
    });

    if (this.searchClearBtn) {
      this.searchClearBtn.addEventListener('click', () => {
        this.searchInput.value = '';
        this.liveSearchResults.classList.remove('active');
        this.searchResultsList.replaceChildren();
        this.searchClearBtn.style.display = 'none';
        this.searchInput.focus();
      });
    }

    document.addEventListener('keydown', event => {
      if ((event.ctrlKey && event.key.toLowerCase() === 'k') ||
        (event.key === '/' && document.activeElement !== this.searchInput)) {
        event.preventDefault();
        this.searchInput.focus();
        this.searchInput.select();
      }
    });
  }

  renderSearchResults(products, query) {
    if (!this.liveSearchResults || !this.searchResultsList) return;
    this.liveSearchResults.classList.add('active');

    if (products.length === 0) {
      this.searchResultsList.innerHTML = `
        <tr><td colspan="6" class="empty-state">No products found for “${this.escapeHtml(query)}”.</td></tr>
      `;
      return;
    }

    this.searchResultsList.innerHTML = products.map(product => {
      const isLow = product.min_threshold > 0 && product.available_stock_quantity <= product.min_threshold;
      const hasSellableStock = product.available_stock_quantity > 0;
      const locations = product.locations.length ? product.locations.join(', ') : '—';
      return `
        <tr>
          <td><strong>${this.escapeHtml(product.name)}</strong><div class="subtle-text">${this.escapeHtml(product.generic_name || '')}</div></td>
          <td>${this.escapeHtml(locations)}</td>
          <td class="text-mono">${this.escapeHtml(product.barcode || '—')}</td>
          <td>${product.stock_quantity.toLocaleString()} on hand<div class="subtle-text">${product.available_stock_quantity.toLocaleString()} sellable · ${product.expired_stock_quantity.toLocaleString()} expired</div></td>
          <td><span class="badge-status ${!hasSellableStock || isLow ? 'badge-status-low-stock' : 'badge-status-in-stock'}">${!hasSellableStock ? 'Unavailable' : isLow ? 'Low stock' : 'Available'}</span></td>
          <td><button class="btn btn-secondary btn-sm" type="button" data-product-id="${product.id}">View</button></td>
        </tr>
      `;
    }).join('');

    this.searchResultsList.querySelectorAll('[data-product-id]').forEach(button => {
      button.addEventListener('click', () => this.app.openProduct(Number(button.dataset.productId)));
    });
  }

  setupClock() {
    const clockEl = document.getElementById('liveClockDisplay');
    if (!clockEl) return;
    const updateTime = () => {
      clockEl.textContent = new Date().toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true
      });
    };
    updateTime();
    setInterval(updateTime, 1000);
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
