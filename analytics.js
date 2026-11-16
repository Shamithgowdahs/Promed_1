/**
 * Owner-only analytics and report export view.
 */
class PromedReports {
  constructor() {
    this.isOwner = false;
    this.bound = false;
    this.range = null;
    this.searchTimer = null;
    this.reportType = document.getElementById('reportsReportType');
    this.searchInput = document.getElementById('reportsSearchInput');
  }

  init(role) {
    this.isOwner = role === 'owner';
    const navLink = document.getElementById('reportsNavLink');
    const view = document.getElementById('view-reports');
    if (navLink) navLink.hidden = !this.isOwner;
    if (view) view.hidden = !this.isOwner;
    if (!this.isOwner || this.bound) return;
    this.bound = true;

    document.getElementById('reportsFilterForm')?.addEventListener('submit', event => {
      event.preventDefault();
      this.load().catch(error => this.setStatus(error.message, true));
    });
    document.getElementById('reportsDatePreset')?.addEventListener('change', event => {
      const custom = event.target.value === 'custom';
      document.getElementById('reportsFromWrap').hidden = !custom;
      document.getElementById('reportsToWrap').hidden = !custom;
    });
    document.getElementById('refreshReportsBtn')?.addEventListener('click', () => {
      this.load().catch(error => this.setStatus(error.message, true));
    });
    document.querySelector('.nav-link[data-view="reports"]')?.addEventListener('click', () => {
      this.load().catch(error => this.setStatus(error.message, true));
    });
    this.reportType?.addEventListener('change', () => {
      this.updateSortOptions([]);
      if (!this.reportColumnsFor(this.reportType.value).includes('category')) {
        document.getElementById('reportsCategoryFilter').value = '';
      }
      this.loadReport().catch(error => this.setStatus(error.message, true));
    });
    this.searchInput?.addEventListener('input', () => {
      clearTimeout(this.searchTimer);
      this.searchTimer = setTimeout(() => {
        this.loadReport().catch(error => this.setStatus(error.message, true));
      }, 250);
    });
    document.getElementById('reportsSortBy')?.addEventListener('change', () => {
      this.loadReport().catch(error => this.setStatus(error.message, true));
    });
    document.getElementById('reportsSortDirection')?.addEventListener('change', () => {
      this.loadReport().catch(error => this.setStatus(error.message, true));
    });
    document.getElementById('reportsCategoryFilter')?.addEventListener('change', () => {
      this.loadReport().catch(error => this.setStatus(error.message, true));
    });
    document.getElementById('exportReportCsvBtn')?.addEventListener('click', () => {
      this.exportReport('csv').catch(error => this.setStatus(error.message, true));
    });
    document.getElementById('exportReportPdfBtn')?.addEventListener('click', () => {
      this.exportReport('pdf').catch(error => this.setStatus(error.message, true));
    });
  }

  async load() {
    if (!this.isOwner) return;
    this.range = this.getDateRange();
    this.setStatus('Loading reports from the database...');
    const [dashboardResult, reportResult] = await Promise.allSettled([
      this.loadDashboard(),
      this.loadReport()
    ]);
    const errors = [dashboardResult, reportResult]
      .filter(result => result.status === 'rejected')
      .map(result => result.reason.message);
    if (errors.length) {
      this.setStatus(errors.join(' '), true);
      return;
    }
    this.setStatus(`Reports loaded for ${this.range.date_from} through ${this.range.date_to}.`);
  }

  getDateRange() {
    const preset = document.getElementById('reportsDatePreset').value;
    const today = new Date();
    const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const start = new Date(end);
    if (preset === 'yesterday') {
      start.setDate(start.getDate() - 1);
      end.setDate(end.getDate() - 1);
    } else if (preset === 'last7') {
      start.setDate(start.getDate() - 6);
    } else if (preset === 'last30') {
      start.setDate(start.getDate() - 29);
    } else if (preset === 'thisMonth') {
      start.setDate(1);
    } else if (preset === 'previousMonth') {
      start.setDate(0);
      end.setTime(start.getTime());
      start.setDate(1);
    } else if (preset === 'custom') {
      const range = {
        date_from: document.getElementById('reportsDateFrom').value,
        date_to: document.getElementById('reportsDateTo').value
      };
      if (!range.date_from || !range.date_to) {
        throw new Error('Choose both a start date and an end date for a custom report range.');
      }
      if (range.date_from > range.date_to) {
        throw new Error('The report start date must be on or before its end date.');
      }
      return range;
    }
    return { date_from: this.localDate(start), date_to: this.localDate(end) };
  }

  localDate(value) {
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
  }

  queryString(extra = {}) {
    const params = new URLSearchParams({ ...(this.range || this.getDateRange()), ...extra });
    return params.toString();
  }

  async request(path) {
    const apiBase = window.PROMED_API_BASE_URL || 'http://127.0.0.1:8000/api';
    const response = await fetch(`${apiBase}${path}`, {
      credentials: 'include',
      headers: { Accept: 'application/json' }
    });
    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      throw new Error(`The analytics API returned invalid JSON: ${error.message}`);
    }
    if (!response.ok) {
      throw new Error(payload?.detail || `Analytics request failed (${response.status})`);
    }
    return payload;
  }

  async loadDashboard() {
    const data = await this.request(`/analytics/dashboard?${this.queryString()}`);
    this.renderDashboard(data);
  }

  async loadReport() {
    if (!this.isOwner || !this.reportType) return;
    this.range = this.range || this.getDateRange();
    const sortBy = document.getElementById('reportsSortBy').value;
    const direction = document.getElementById('reportsSortDirection').value;
    const search = this.searchInput.value.trim();
    const params = { ...(this.range), direction };
    const category = document.getElementById('reportsCategoryFilter').value;
    if (sortBy) params.sort_by = sortBy;
    if (search) params.search = search;
    if (category) params.category = category;
    const data = await this.request(`/analytics/reports/${encodeURIComponent(this.reportType.value)}?${new URLSearchParams(params)}`);
    this.renderReport(data);
  }

  renderDashboard(data) {
    const currency = data.currency_code;
    const sales = data.sales;
    const inventory = data.inventory;
    this.text('reportNetRevenue', this.money(sales.net_revenue, currency));
    this.text('reportTransactionCount', this.integer(sales.transaction_count));
    this.text('reportAverageTransaction', this.money(sales.average_transaction, currency));
    this.text('reportUnitsSold', this.integer(sales.units_sold));
    this.text('reportOrderCount', this.integer(Object.values(data.order_workflow).reduce((sum, count) => sum + count, 0)));
    this.text('reportEligibleStock', this.integer(inventory.eligible_units));
    this.text('reportActiveProducts', this.integer(inventory.active_products));
    this.text('reportLowStockCount', this.integer(inventory.low_stock_products));

    this.text('reportGrossProfit', data.profit.calculable
      ? this.money(data.profit.estimated_gross_profit, currency)
      : 'Not calculable');
    this.text('reportProfitNote', data.profit.calculable
      ? 'Estimate from currently recorded batch costs'
      : `${this.integer(data.profit.missing_cost_units)} sold units have no recorded cost`);
    this.text('reportInventoryValue', inventory.recorded_cost_value === null
      ? 'Incomplete'
      : this.money(inventory.recorded_cost_value, currency));
    this.text('reportInventoryValueNote', inventory.missing_cost_units
      ? `${this.integer(inventory.missing_cost_units)} on-hand units lack recorded cost`
      : 'Recorded batch cost for all on-hand units');

    this.renderTrend(data.sales_trend, currency);
    this.renderExpiry(data.expiry);
    this.renderBestSellers(data.best_sellers, currency);
    this.renderCategories(data.category_performance, currency);
    this.renderOrderWorkflow(data.order_workflow);
    this.renderPurchases(data);
    this.renderNotes(data.notes);
    this.setCategoryOptions(data.categories || []);
  }

  renderTrend(trend, currency) {
    const container = document.getElementById('reportsTrendChart');
    const points = trend.points || [];
    if (!points.some(point => point.sales > 0)) {
      container.innerHTML = '<p class="report-chart-empty">No sales have been recorded for this date range.</p>';
      return;
    }
    const width = Math.max(640, points.length * 52);
    const height = 210;
    const top = 24;
    const bottom = 38;
    const chartHeight = height - top - bottom;
    const max = Math.max(...points.map(point => point.sales), 1);
    const step = width / points.length;
    const barWidth = Math.max(8, Math.min(28, step * 0.58));
    const bars = points.map((point, index) => {
      const barHeight = Math.max(1, (point.sales / max) * chartHeight);
      const x = index * step + (step - barWidth) / 2;
      const y = top + chartHeight - barHeight;
      const label = trend.period === 'month' ? point.period : point.period.slice(5);
      return `<g><title>${this.escape(`${label}: ${this.money(point.sales, currency)}`)}</title><rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}" rx="4" fill="var(--color-accent, #3b82f6)"/><text x="${(index * step + step / 2).toFixed(1)}" y="${height - 12}" text-anchor="middle" fill="currentColor" font-size="10">${this.escape(label)}</text></g>`;
    }).join('');
    container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Recorded sales trend"><line x1="0" y1="${top + chartHeight}" x2="${width}" y2="${top + chartHeight}" stroke="currentColor" opacity=".2"/>${bars}</svg>`;
  }

  renderExpiry(expiry) {
    const labels = [
      ['expired', 'Expired'],
      ['within_7_days', 'Within 7 days'],
      ['within_30_days', '8–30 days'],
      ['within_60_days', '31–60 days'],
      ['within_90_days', '61–90 days']
    ];
    document.getElementById('reportsExpirySummary').innerHTML = labels.map(([key, label]) =>
      `<div class="reports-expiry-item"><span>${label}</span><strong>${this.integer(expiry[key])} units</strong></div>`
    ).join('');
  }

  renderBestSellers(rows, currency) {
    const body = document.getElementById('reportBestSellers');
    body.innerHTML = rows.length ? rows.map(row => `<tr>
      <td>${this.escape(row.product_name)}</td><td>${this.escape(row.category)}</td>
      <td>${this.integer(row.units_sold)}</td><td>${this.money(row.net_sales_ex_tax, currency)}</td>
      <td>${row.estimated_gross_profit === null ? 'Not calculable' : this.money(row.estimated_gross_profit, currency)}</td>
    </tr>`).join('') : '<tr><td colspan="5" class="empty-state">No product sales are recorded for this period.</td></tr>';
  }

  renderCategories(rows, currency) {
    const body = document.getElementById('reportCategoryPerformance');
    body.innerHTML = rows.length ? rows.map(row => `<tr>
      <td>${this.escape(row.category)}</td><td>${this.integer(row.units_sold)}</td><td>${this.money(row.net_sales_ex_tax, currency)}</td>
    </tr>`).join('') : '<tr><td colspan="3" class="empty-state">No category sales are recorded for this period.</td></tr>';
  }

  renderOrderWorkflow(statuses) {
    const entries = Object.entries(statuses);
    document.getElementById('reportOrderWorkflow').innerHTML = entries.length
      ? entries.map(([status, count]) => `<div class="reports-status-item"><span>${this.escape(status.replaceAll('_', ' '))}</span><strong>${this.integer(count)}</strong></div>`).join('')
      : '<p class="empty-state">No customer orders were created during this period.</p>';
  }

  renderPurchases(data) {
    const purchase = data.purchase_summary;
    document.getElementById('reportPurchaseSummary').textContent =
      `${this.integer(purchase.record_count)} batch purchase records; recorded value ${this.money(purchase.recorded_purchase_value, data.currency_code)}. ${this.integer(purchase.unpriced_batch_count)} record(s) have no purchase price.`;
    const rows = data.purchase_records || [];
    const body = document.getElementById('reportRecentReceipts');
    body.innerHTML = rows.length ? rows.slice(0, 10).map(row => `<tr>
      <td>${this.escape(row.purchase_date)}</td><td>${this.escape(row.product_name)}</td><td>${this.escape(row.batch_number)}</td>
      <td>${this.integer(row.received_quantity)}</td><td>${row.recorded_purchase_value === null ? 'Not recorded' : this.money(row.recorded_purchase_value, data.currency_code)}</td>
    </tr>`).join('') : '<tr><td colspan="5" class="empty-state">No batch purchase records exist in this period.</td></tr>';
  }

  renderNotes(notes) {
    document.getElementById('reportsNotes').innerHTML = notes.map(note => `<li>${this.escape(note)}</li>`).join('');
  }

  renderReport(data) {
    this.updateSortOptions(data.columns);
    const categoryFilter = document.getElementById('reportsCategoryFilter');
    const categoryEnabled = data.columns.includes('category');
    categoryFilter.disabled = !categoryEnabled;
    if (!categoryEnabled) categoryFilter.value = '';
    this.setCategoryOptions(data.categories || []);
    const head = document.getElementById('reportsTableHead');
    const body = document.getElementById('reportsTableBody');
    head.innerHTML = `<tr>${data.columns.map(column => `<th>${this.escape(column.replaceAll('_', ' '))}</th>`).join('')}</tr>`;
    body.innerHTML = data.rows.length ? data.rows.map(row => `<tr>${data.columns.map(column =>
      `<td>${this.escape(row[column] === null ? 'Not calculable' : row[column] === undefined ? '' : String(row[column]))}</td>`
    ).join('')}</tr>`).join('') : `<tr><td colspan="${data.columns.length}" class="empty-state">No saved records match this report and date range.</td></tr>`;
    const limitNote = data.truncated ? ` Showing the first ${data.row_limit.toLocaleString()} matching rows; narrow the filters to see a smaller set.` : '';
    document.getElementById('reportsTableNote').textContent =
      `${data.rows.length.toLocaleString()} row(s)${data.warning ? ` · ${data.warning}` : ''}${limitNote}`;
  }

  updateSortOptions(columns) {
    const select = document.getElementById('reportsSortBy');
    if (!select) return;
    const current = select.value;
    const options = columns.length ? columns : this.reportColumnsFor(this.reportType?.value);
    select.innerHTML = `<option value="">Default</option>${options.map(column =>
      `<option value="${this.escape(column)}">${this.escape(column.replaceAll('_', ' '))}</option>`
    ).join('')}`;
    if (options.includes(current)) select.value = current;
  }

  setCategoryOptions(categories) {
    const select = document.getElementById('reportsCategoryFilter');
    if (!select) return;
    const current = select.value;
    select.innerHTML = `<option value="">All categories</option>${categories.map(category =>
      `<option value="${this.escape(category)}">${this.escape(category)}</option>`
    ).join('')}`;
    if (categories.includes(current)) select.value = current;
  }

  reportColumnsFor(type) {
    const columns = {
      sales: ['invoice_number', 'date', 'item_count', 'subtotal', 'discount', 'tax', 'total', 'refunds', 'net_revenue'],
      revenue: ['invoice_number', 'date', 'item_count', 'subtotal', 'discount', 'tax', 'total', 'refunds', 'net_revenue'],
      profit: ['product_id', 'product_name', 'category', 'units_sold', 'net_sales_ex_tax', 'estimated_cost', 'estimated_gross_profit', 'missing_cost_units', 'profit_calculable'],
      inventory: ['product_id', 'product_name', 'category', 'active', 'stock_units', 'eligible_stock_units', 'recorded_inventory_cost', 'missing_cost_units', 'min_threshold', 'low_stock'],
      'inventory-by-location': ['product_id', 'product_name', 'category', 'location_code', 'location_name', 'on_hand_units', 'eligible_stock_units', 'recorded_inventory_cost', 'missing_cost_units'],
      'low-stock': ['product_id', 'product_name', 'category', 'active', 'stock_units', 'eligible_stock_units', 'recorded_inventory_cost', 'missing_cost_units', 'min_threshold', 'low_stock'],
      expiry: ['product_name', 'category', 'batch_number', 'expiry_date', 'days_remaining', 'quantity', 'status', 'location_code'],
      'supplier-purchases': ['supplier_name', 'purchase_date', 'product_name', 'batch_number', 'location_code', 'received_quantity', 'purchase_price', 'unit_cost', 'recorded_purchase_value', 'value_source'],
      'customer-orders': ['order_number', 'date', 'status', 'workflow_status', 'fulfillment_method', 'item_count', 'total_amount'],
      'stock-movement': ['date', 'product_name', 'batch_number', 'location_code', 'kind', 'quantity_delta', 'previous_quantity', 'updated_quantity', 'reason']
    };
    return columns[type] || [];
  }

  async exportReport(format) {
    if (!this.isOwner) return;
    this.range = this.range || this.getDateRange();
    const params = {
      ...this.range,
      format,
      direction: document.getElementById('reportsSortDirection').value
    };
    const sortBy = document.getElementById('reportsSortBy').value;
    const search = this.searchInput.value.trim();
    const category = document.getElementById('reportsCategoryFilter').value;
    if (sortBy) params.sort_by = sortBy;
    if (search) params.search = search;
    if (category) params.category = category;
    const base = window.PROMED_API_BASE_URL || 'http://127.0.0.1:8000/api';
    const response = await fetch(`${base}/analytics/reports/${encodeURIComponent(this.reportType.value)}/export?${new URLSearchParams(params)}`, {
      credentials: 'include'
    });
    if (!response.ok) {
      let detail = `Report export failed (${response.status})`;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch (error) {
        detail += `: ${error.message}`;
      }
      throw new Error(detail);
    }
    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const filename = disposition.match(/filename="([^"]+)"/)?.[1] || `promed-${this.reportType.value}.${format}`;
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
    this.setStatus(`${format.toUpperCase()} report exported.`);
  }

  text(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  setStatus(message, isError = false) {
    const status = document.getElementById('reportsStatus');
    if (!status) return;
    status.textContent = message;
    status.classList.toggle('is-error', isError);
  }

  money(value, currency) {
    const amount = Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return currency ? `${currency} ${amount}` : amount;
  }

  integer(value) {
    return Number(value || 0).toLocaleString();
  }

  escape(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[character]);
  }
}
