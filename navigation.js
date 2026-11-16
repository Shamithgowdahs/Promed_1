/**
 * PROMED — Smart Medical Store Management System
 * Navigation & View Management Module
 */

class PromedNavigation {
  constructor() {
    this.sidebar = document.getElementById('appSidebar');
    this.mobileToggle = document.getElementById('mobileMenuToggle');
    this.backdrop = document.getElementById('sidebarBackdrop');
    this.navLinks = document.querySelectorAll('.nav-link');
    this.brandLink = document.querySelector('.brand[data-view]');
    this.viewPanels = document.querySelectorAll('.view-panel');
    this.headerTitle = document.getElementById('headerViewTitle');
    this.headerSubtitle = document.getElementById('headerViewSubtitle');

    this.viewMeta = {
      'dashboard': {
        title: 'Pharmacy Dashboard',
        subtitle: 'Overview of stock, activity, and storage box allocations'
      },
      'inventory': {
        title: 'Medicine Inventory',
        subtitle: 'Registered pharmaceuticals, batch tracks, and shelf allocations'
      },
      'products': {
        title: 'Product Management',
        subtitle: 'Owner-only product, category, image, and batch setup'
      },
      'scan': {
        title: 'Scan Medicine',
        subtitle: 'Direct barcode input and hardware scanner interface'
      },
      'sales': {
        title: 'Dispensing & Sales',
        subtitle: 'FEFO point of sale, invoice history, payments, and returns'
      },
      'orders': {
        title: 'Customer Orders',
        subtitle: 'Pharmacist review, pickup, delivery, and order history'
      },
      'expiry': {
        title: 'Expiry Management',
        subtitle: 'FEFO tracking (First Expiry First Out) and shelf inspections'
      },
      'reorder': {
        title: 'Reorder Suggestions',
        subtitle: 'Smart inventory replenishment suggestions based on minimum stock'
      },
      'reports': {
        title: 'Pharmacy Analytics & Reports',
        subtitle: 'Movement trends, audit logs, and consumption rates'
      },
      'settings': {
        title: 'System Settings',
        subtitle: 'Pharmacy configuration, storage box mapping, and hardware setup'
      }
    };

    this.init();
  }

  init() {
    // Attach click listeners to all navigation links
    this.navLinks.forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const targetView = link.getAttribute('data-view');
        if (targetView) {
          this.navigateTo(targetView);
          // If on mobile, auto-close sidebar on click
          this.closeMobileSidebar();
        }
      });
    });

    if (this.brandLink) {
      this.brandLink.addEventListener('click', (e) => {
        e.preventDefault();
        this.navigateTo('dashboard');
        this.closeMobileSidebar();
      });
    }

    // Mobile sidebar toggle handlers
    if (this.mobileToggle) {
      this.mobileToggle.addEventListener('click', () => this.toggleMobileSidebar());
    }

    if (this.backdrop) {
      this.backdrop.addEventListener('click', () => this.closeMobileSidebar());
    }

    // Keyboard navigation helper (Esc closes mobile menu or modal)
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        this.closeMobileSidebar();
      }
    });
  }

  navigateTo(viewId) {
    // 1. Update navigation active state
    this.navLinks.forEach(link => {
      if (link.getAttribute('data-view') === viewId) {
        link.classList.add('active');
      } else {
        link.classList.remove('active');
      }
    });

    // 2. Switch visible view panel
    this.viewPanels.forEach(panel => {
      if (panel.id === `view-${viewId}`) {
        panel.classList.add('active-view');
      } else {
        panel.classList.remove('active-view');
      }
    });

    // 3. Update header breadcrumb/title
    if (this.viewMeta[viewId]) {
      if (this.headerTitle) this.headerTitle.textContent = this.viewMeta[viewId].title;
      if (this.headerSubtitle) this.headerSubtitle.textContent = this.viewMeta[viewId].subtitle;
    }

    // 4. Scroll main content area back to top
    const contentArea = document.querySelector('.content-area');
    if (contentArea) {
      contentArea.scrollTop = 0;
    }
  }

  toggleMobileSidebar() {
    if (this.sidebar) {
      const isOpen = this.sidebar.classList.toggle('open');
      if (this.backdrop) {
        this.backdrop.classList.toggle('active', isOpen);
      }
    }
  }

  closeMobileSidebar() {
    if (this.sidebar && this.sidebar.classList.contains('open')) {
      this.sidebar.classList.remove('open');
      if (this.backdrop) {
        this.backdrop.classList.remove('active');
      }
    }
  }
}
