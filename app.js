/**
 * PROMED — Smart Medical Store Management System
 * Main Application Orchestrator (Step 1)
 */

class PromedApplication {
  constructor() {
    this.demoData = PROMED_DEMO_DATA;
    this.nav = null;
    this.dashboard = null;

    // Modal elements
    this.barcodeModal = document.getElementById('barcodeModal');
    this.barcodeInput = document.getElementById('modalBarcodeInput');
    this.barcodeResult = document.getElementById('barcodeResultCard');
    this.barcodeLookupBtn = document.getElementById('barcodeLookupBtn');

    this.init();
  }

  init() {
    // 1. Initialize Navigation Controller
    this.nav = new PromedNavigation();

    // 2. Initialize Dashboard Controller
    this.dashboard = new PromedDashboard(this.demoData);

    // 3. Set up Quick-Action Buttons
    this.setupQuickActions();

    // 4. Set up Barcode Scanner Modal Handlers
    this.setupBarcodeModal();

    // 5. Populate Secondary Prototype Views with Demo Content
    this.populateInventoryView();

    console.info("PROMED Pharmacy System (Step 1 Prototype) initialized with DEMO DATA.");
  }

  setupQuickActions() {
    // Button: Open Medicine Inventory
    const openInventoryBtn = document.getElementById('btnQuickOpenInventory');
    if (openInventoryBtn) {
      openInventoryBtn.addEventListener('click', () => {
        this.nav.navigateTo('inventory');
      });
    }

    // Button: Scan / Enter Barcode
    const scanBarcodeBtn = document.getElementById('btnQuickScanBarcode');
    if (scanBarcodeBtn) {
      scanBarcodeBtn.addEventListener('click', () => {
        this.openBarcodeModal();
      });
    }
  }

  setupBarcodeModal() {
    if (!this.barcodeModal) return;

    // Close buttons
    const closeBtns = this.barcodeModal.querySelectorAll('[data-close-modal]');
    closeBtns.forEach(btn => {
      btn.addEventListener('click', () => this.closeBarcodeModal());
    });

    // Close on overlay backdrop click
    this.barcodeModal.addEventListener('click', (e) => {
      if (e.target === this.barcodeModal) {
        this.closeBarcodeModal();
      }
    });

    // Lookup button
    if (this.barcodeLookupBtn) {
      this.barcodeLookupBtn.addEventListener('click', () => {
        this.performBarcodeLookup(this.barcodeInput.value.trim());
      });
    }

    // Enter key triggers lookup
    if (this.barcodeInput) {
      this.barcodeInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this.performBarcodeLookup(this.barcodeInput.value.trim());
        }
      });
    }

    // Demo barcode sample chips
    const sampleChips = document.querySelectorAll('.barcode-chip');
    sampleChips.forEach(chip => {
      chip.addEventListener('click', () => {
        const code = chip.getAttribute('data-barcode');
        if (code) {
          this.barcodeInput.value = code;
          this.performBarcodeLookup(code);
        }
      });
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
      if (this.barcodeResult) this.barcodeResult.classList.remove('active');
    }

    setTimeout(() => {
      if (this.barcodeInput) this.barcodeInput.focus();
    }, 100);
  }

  closeBarcodeModal() {
    if (!this.barcodeModal) return;
    this.barcodeModal.classList.remove('active');
  }

  performBarcodeLookup(barcode) {
    if (!barcode || !this.barcodeResult) return;

    // Search in demo medicines list
    const found = this.demoData.medicinesList.find(m => m.barcode === barcode);

    if (found) {
      // Find storage box details
      const box = this.demoData.storageBoxes.find(b => b.id === found.storageBox);
      const boxCategory = box ? box.category : "General Rack";

      this.barcodeResult.innerHTML = `
        <div class="barcode-result-header">
          <span class="badge-status badge-status-in-stock">Item Found in Demo Catalog</span>
          <span class="demo-tag demo-tag-sm">DEMO SIMULATION</span>
        </div>
        <div class="barcode-medicine-name">${this.escapeHtml(found.name)}</div>
        <div style="font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 8px;">
          ${this.escapeHtml(found.generic)} • <span class="text-mono">Batch ${found.batchNumber}</span>
        </div>

        <div class="barcode-location-callout">
          <div class="callout-box-indicator">
            <span class="led-indicator-dot" style="background-color: ${box ? box.colorCode : '#10b981'}; box-shadow: 0 0 10px ${box ? box.colorCode : '#10b981'};"></span>
            Box ${found.storageBox}
          </div>
          <div class="callout-details">
            <div><strong>Location:</strong> ${this.escapeHtml(found.shelfRow)}</div>
            <div><strong>Category:</strong> ${this.escapeHtml(boxCategory)}</div>
            <div><strong>Status:</strong> LED Pulse Active on Box Rack (Phase 4 Simulation)</div>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; font-size: 0.76rem; margin-top: 10px; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px;">
          <div>
            <div style="color: var(--text-muted);">Current Stock:</div>
            <strong style="color: var(--text-white); font-size: 0.9rem;">${found.stockQuantity} units</strong>
          </div>
          <div>
            <div style="color: var(--text-muted);">Unit Price:</div>
            <strong style="color: var(--color-accent-light); font-size: 0.9rem;">$${found.unitPrice.toFixed(2)}</strong>
          </div>
          <div>
            <div style="color: var(--text-muted);">Expiry Date:</div>
            <strong style="color: var(--text-white); font-size: 0.9rem;">${found.expiryDate}</strong>
          </div>
        </div>
      `;
      this.barcodeResult.classList.add('active');
    } else {
      this.barcodeResult.innerHTML = `
        <div style="text-align: center; padding: 12px; color: var(--status-warning);">
          <strong>Barcode Not Found in Demo Dataset: "${this.escapeHtml(barcode)}"</strong>
          <p style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">
            Please select one of the sample demonstration barcodes above (Augmentin, Dolo 650, Salbutamol, etc.).
          </p>
        </div>
      `;
      this.barcodeResult.classList.add('active');
    }
  }

  populateInventoryView() {
    const tableBody = document.getElementById('inventoryTableBody');
    if (!tableBody) return;

    tableBody.innerHTML = this.demoData.medicinesList.map(med => {
      const isLow = med.stockQuantity <= med.minThreshold;
      const statusBadge = isLow
        ? `<span class="badge-status badge-status-low-stock">Low Stock</span>`
        : `<span class="badge-status badge-status-in-stock">Normal</span>`;

      return `
        <tr>
          <td>
            <strong>${this.escapeHtml(med.name)}</strong>
            <div style="font-size: 0.72rem; color: var(--text-muted);">${this.escapeHtml(med.generic)}</div>
          </td>
          <td><span class="text-mono" style="font-size: 0.78rem;">${this.escapeHtml(med.barcode)}</span></td>
          <td>${this.escapeHtml(med.category)}</td>
          <td><span class="location-badge">Box ${this.escapeHtml(med.storageBox)}</span> <span style="font-size: 0.72rem; color: var(--text-muted);">${this.escapeHtml(med.shelfRow)}</span></td>
          <td><strong>${med.stockQuantity}</strong> <span style="font-size: 0.72rem; color: var(--text-muted);">units</span></td>
          <td>$${med.unitPrice.toFixed(2)}</td>
          <td><span class="text-mono" style="font-size: 0.75rem;">${med.expiryDate}</span></td>
          <td>${statusBadge}</td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="window.PromedApp.openBarcodeModal('${med.barcode}')">
              Box LED
            </button>
          </td>
        </tr>
      `;
    }).join('');
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

// Instantiate on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  window.PromedApp = new PromedApplication();
});
