/**
 * PROMED — Smart Medical Store Management System
 * Dashboard Controller Module
 */

class PromedDashboard {
  constructor(demoData) {
    this.data = demoData;
    this.searchInput = document.getElementById('medicineSearchInput');
    this.searchClearBtn = document.getElementById('searchClearBtn');
    this.liveSearchResults = document.getElementById('liveSearchResults');
    this.searchResultsList = document.getElementById('searchResultsList');
    this.storageBoxesContainer = document.getElementById('storageBoxesContainer');
    this.activityFeedContainer = document.getElementById('activityFeedContainer');

    this.init();
  }

  init() {
    this.renderMetrics();
    this.renderStorageBoxes();
    this.renderActivityFeed();
    this.setupSearch();
    this.setupClock();
  }

  renderMetrics() {
    const { metrics } = this.data;

    // Total registered medicines
    const regMedEl = document.getElementById('metricRegisteredMedicines');
    if (regMedEl) {
      regMedEl.textContent = metrics.totalRegisteredMedicines.toLocaleString();
    }

    // Total available stock
    const availStockEl = document.getElementById('metricAvailableStock');
    if (availStockEl) {
      availStockEl.textContent = metrics.totalAvailableStock.toLocaleString();
    }

    // Today's sales summary
    const todaySalesEl = document.getElementById('metricTodaySales');
    if (todaySalesEl) {
      todaySalesEl.textContent = `${metrics.todaySalesSummary.currency}${metrics.todaySalesSummary.totalAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    // Low stock count
    const lowStockEl = document.getElementById('metricLowStock');
    if (lowStockEl) {
      lowStockEl.textContent = metrics.lowStockCount;
    }
  }

  renderStorageBoxes() {
    if (!this.storageBoxesContainer) return;

    this.storageBoxesContainer.innerHTML = '';

    this.data.storageBoxes.forEach(box => {
      const boxCard = document.createElement('div');
      boxCard.className = 'storage-box-item';
      boxCard.setAttribute('data-box-id', box.id);

      // Pill color indicator for fill level
      let progressColor = '#10b981'; // Green
      if (box.percentage > 85) progressColor = '#a78bfa'; // Purple / High
      if (box.percentage < 50) progressColor = '#f59e0b'; // Amber / Low fill

      const samplePills = box.sampleMedicines
        .map(med => `<span class="box-pill-tag">${this.escapeHtml(med.name)} (${med.stock})</span>`)
        .join('');

      boxCard.innerHTML = `
        <div class="box-header">
          <span class="box-code-pill ${box.accentClass}">
            <span class="led-indicator-dot"></span>
            ${box.label}
          </span>
          <span class="demo-tag demo-tag-sm">DEMO BOX</span>
        </div>
        <div class="box-category-title">${this.escapeHtml(box.category)}</div>
        <div class="box-description">Zone: ${this.escapeHtml(box.temperatureZone)} • LED: <span class="text-accent">${this.escapeHtml(box.ledStatus)}</span></div>

        <div class="box-progress-container">
          <div class="box-progress-bar-bg">
            <div class="box-progress-bar-fill" style="width: ${box.percentage}%; background-color: ${progressColor};"></div>
          </div>
        </div>

        <div class="box-meta-footer">
          <span>Capacity: <strong>${box.currentOccupancy} / ${box.totalCapacity} slots</strong></span>
          <span style="color: ${progressColor}; font-weight: 700;">${box.percentage}% utilized</span>
        </div>

        <div class="box-sample-medicines">
          ${samplePills}
        </div>
      `;

      // Interactive click to inspect or highlight box medicines in search
      boxCard.addEventListener('click', () => {
        this.filterByBox(box.id, box.label);
      });

      this.storageBoxesContainer.appendChild(boxCard);
    });
  }

  filterByBox(boxId, boxLabel) {
    if (this.searchInput) {
      this.searchInput.value = `Box ${boxId}`;
      this.handleSearch(`Box ${boxId}`);
    }
  }

  renderActivityFeed() {
    if (!this.activityFeedContainer) return;

    this.activityFeedContainer.innerHTML = '';

    this.data.recentActivity.forEach(item => {
      const feedItem = document.createElement('div');
      feedItem.className = 'activity-item';

      let iconHtml = `
        <div class="activity-icon-badge activity-icon-sale">
          <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z"/>
          </svg>
        </div>
      `;

      if (item.iconType === 'alert') {
        iconHtml = `
          <div class="activity-icon-badge activity-icon-alert">
            <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
            </svg>
          </div>
        `;
      } else if (item.iconType === 'scan') {
        iconHtml = `
          <div class="activity-icon-badge activity-icon-scan">
            <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v1m6 11h2m-6 0h-2v4m0-11v3m0 0h.01M12 12h4.01M16 20h4M4 12h4m12 0h.01M5 8h2a1 1 0 001-1V5a1 1 0 00-1-1H5a1 1 0 00-1 1v2a1 1 0 001 1zm12 0h2a1 1 0 001-1V5a1 1 0 00-1-1h-2a1 1 0 00-1 1v2a1 1 0 001 1zM5 20h2a1 1 0 001-1v-2a1 1 0 00-1-1H5a1 1 0 00-1 1v2a1 1 0 001 1z"/>
            </svg>
          </div>
        `;
      }

      feedItem.innerHTML = `
        ${iconHtml}
        <div class="activity-content">
          <div class="activity-title">
            <span>${this.escapeHtml(item.title)}</span>
            <span class="location-badge">${this.escapeHtml(item.boxTag)}</span>
          </div>
          <div class="activity-detail">${this.escapeHtml(item.detail)}</div>
          <div class="activity-time">${this.escapeHtml(item.time)} • Demo Activity Log</div>
        </div>
      `;

      this.activityFeedContainer.appendChild(feedItem);
    });
  }

  setupSearch() {
    if (!this.searchInput) return;

    this.searchInput.addEventListener('input', (e) => {
      const query = e.target.value.trim();
      this.handleSearch(query);
    });

    if (this.searchClearBtn) {
      this.searchClearBtn.addEventListener('click', () => {
        this.searchInput.value = '';
        this.handleSearch('');
        this.searchInput.focus();
      });
    }

    // Keyboard shortcut (Ctrl+K or Slash to focus search)
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey && e.key.toLowerCase() === 'k') || (e.key === '/' && document.activeElement !== this.searchInput)) {
        e.preventDefault();
        this.searchInput.focus();
        this.searchInput.select();
      }
    });
  }

  handleSearch(query) {
    if (!this.liveSearchResults || !this.searchResultsList) return;

    if (!query) {
      this.liveSearchResults.classList.remove('active');
      if (this.searchClearBtn) this.searchClearBtn.style.display = 'none';
      return;
    }

    if (this.searchClearBtn) this.searchClearBtn.style.display = 'block';

    const normalizedQuery = query.toLowerCase();

    // Search against medicinesList and storageBoxes
    const results = this.data.medicinesList.filter(med => {
      return (
        med.name.toLowerCase().includes(normalizedQuery) ||
        med.generic.toLowerCase().includes(normalizedQuery) ||
        med.category.toLowerCase().includes(normalizedQuery) ||
        med.barcode.includes(normalizedQuery) ||
        med.storageBox.toLowerCase() === normalizedQuery.replace('box ', '') ||
        `box ${med.storageBox}`.toLowerCase().includes(normalizedQuery)
      );
    });

    this.renderSearchResults(results, query);
  }

  renderSearchResults(results, query) {
    this.liveSearchResults.classList.add('active');

    if (results.length === 0) {
      this.searchResultsList.innerHTML = `
        <tr>
          <td colspan="6" style="text-align: center; padding: 24px; color: var(--text-muted);">
            No demonstration medicines found matching "<strong>${this.escapeHtml(query)}</strong>".
            <br><small style="color: var(--text-secondary); margin-top: 4px; display: inline-block;">
              Try searching for "Augmentin", "Dolo", "Inhaler", or "Box A1".
            </small>
          </td>
        </tr>
      `;
      return;
    }

    this.searchResultsList.innerHTML = results.map(med => {
      const isLow = med.stockQuantity <= med.minThreshold;
      const statusBadge = isLow
        ? `<span class="badge-status badge-status-low-stock">Low Stock (${med.stockQuantity})</span>`
        : `<span class="badge-status badge-status-in-stock">In Stock (${med.stockQuantity})</span>`;

      return `
        <tr>
          <td>
            <strong>${this.escapeHtml(med.name)}</strong>
            <div style="font-size: 0.72rem; color: var(--text-muted);">${this.escapeHtml(med.generic)}</div>
          </td>
          <td><span class="location-badge">Box ${this.escapeHtml(med.storageBox)}</span> <span style="font-size: 0.72rem; color: var(--text-muted);">${this.escapeHtml(med.shelfRow)}</span></td>
          <td><span class="text-mono" style="font-size: 0.75rem;">${this.escapeHtml(med.barcode)}</span></td>
          <td><strong>${med.stockQuantity}</strong> <span style="font-size: 0.72rem; color: var(--text-muted);">units</span></td>
          <td>${statusBadge}</td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="window.PromedApp.openBarcodeModal('${med.barcode}')">
              Locate Box
            </button>
          </td>
        </tr>
      `;
    }).join('');
  }

  setupClock() {
    const clockEl = document.getElementById('liveClockDisplay');
    if (!clockEl) return;

    const updateTime = () => {
      const now = new Date();
      const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
      clockEl.textContent = timeStr;
    };

    updateTime();
    setInterval(updateTime, 1000);
  }

  escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
}
