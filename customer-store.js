(function () {
  const categoryDefinitions = [
    { slug: 'medicines', name: 'Medicines', description: 'Medicines and pharmacist-reviewed essentials.', aliases: ['medicine', 'medications', 'pharmacy products'], image_url: './assets/categories/medicines.jpg', tint: '#e5f1ed', ink: '#25836d' },
    { slug: 'creams-gels', name: 'Creams & Gels', description: 'Topical creams, gels and ointments.', aliases: ['cream', 'creams', 'gel', 'gels', 'creams and gels', 'topical products', 'ointments'], image_url: './assets/categories/creams-gels.jpg', tint: '#f7ede3', ink: '#b77c48' },
    { slug: 'first-aid-wound-care', name: 'First Aid & Wound Care', description: 'Bandages and first-aid supplies.', aliases: ['first aid', 'wound care', 'bandages', 'first aid and wound care'], image_url: './assets/categories/first-aid.jpg', tint: '#f5e8e4', ink: '#bb715d' },
    { slug: 'personal-care', name: 'Personal Care', description: 'Everyday personal-care essentials.', aliases: ['personal care', 'personal hygiene', 'toiletries'], image_url: './assets/categories/personal-care.jpg', tint: '#edf0e3', ink: '#668056' },
    { slug: 'baby-care', name: 'Baby Care', description: 'Baby-care products and essentials.', aliases: ['baby', 'infant care', 'baby products'], image_url: './assets/categories/baby-care.jpg', tint: '#f5ede7', ink: '#a97a70' },
    { slug: 'health-nutrition', name: 'Health & Nutrition', description: 'Health and nutrition products.', aliases: ['health nutrition', 'health and nutrition', 'nutrition', 'nutritional products'], image_url: './assets/categories/health-nutrition.jpg', tint: '#f1eee0', ink: '#a1803e' },
    { slug: 'vitamins-minerals', name: 'Vitamins & Minerals', description: 'Vitamins and minerals.', aliases: ['vitamins', 'minerals', 'vitamin', 'vitamins and minerals', 'mineral supplements'], image_url: './assets/categories/vitamins-minerals.jpg', tint: '#f4e9e7', ink: '#ad6459' },
    { slug: 'medical-equipment', name: 'Medical Equipment', description: 'Thermometers and medical equipment.', aliases: ['medical equipment', 'medical devices', 'equipment'], image_url: './assets/categories/medical-equipment.jpg', tint: '#e8eff0', ink: '#4a7b86' },
    { slug: 'hygiene-sanitary-products', name: 'Hygiene & Sanitary Products', description: 'Hygiene and sanitary essentials.', aliases: ['hygiene', 'sanitary products', 'feminine hygiene', 'sanitary', 'hygiene and sanitary products', 'sanitary and hygiene products'], image_url: './assets/categories/hygiene-sanitary.jpg', tint: '#e6efec', ink: '#3b8b79' }
  ];
  let categories = categoryDefinitions.map(category => ({
    ...category,
    id: null,
    database_category_ids: []
  }));
  let products = [];
  const productCache = new Map();

  const state = {
    cart: readCart(),
    theme: localStorage.getItem('promed-store-theme') === 'dark' ? 'dark' : 'light',
    shopSearch: '',
    shopCategory: 'all',
    shopAvailability: 'all',
    shopSort: 'name-asc',
    fulfillment: 'pickup',
    customer: null,
    catalogError: '',
    catalogMetadataError: '',
    catalogStatusError: '',
    catalogStatus: null,
    trackResult: null,
    accountOrders: [],
    authError: ''
  };

  const storeContent = document.getElementById('storeContent');
  const themeToggle = document.getElementById('themeToggle');
  const menuToggle = document.getElementById('storeMenuToggle');
  const navigation = document.getElementById('storeNavigation');
  const toast = document.getElementById('storeToast');
  let toastTimer;
  let searchTimer;
  let checkoutKey = null;
  let trackReference = '';

  function readCart() {
    try {
      const saved = JSON.parse(localStorage.getItem('promed-store-basket') || '{}');
      if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
        return Object.keys(saved).reduce((cart, id) => {
          const quantity = Number(saved[id]);
          if (/^\d+$/.test(id) && Number.isInteger(quantity) && quantity > 0 && quantity <= 99) {
            cart[id] = quantity;
          }
          return cart;
        }, {});
      }
    } catch (error) {
      console.warn('Could not restore the customer preview basket.', error);
    }
    return {};
  }

  function saveCart() {
    try {
      localStorage.setItem('promed-store-basket', JSON.stringify(state.cart));
    } catch (error) {
      console.error('Could not save the customer preview basket.', error);
      showToast('This browser could not save the preview basket.');
    }
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, character => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    })[character]);
  }

  function money(amount) {
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(amount);
  }

  function normalizeCategoryName(value) {
    return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  }

  function categoryFor(product) {
    const categoryId = Number(product.category_id);
    return categories.find(category =>
      Number(category.id) === categoryId ||
      category.database_category_ids.some(id => Number(id) === categoryId)
    ) || categories.find(category => {
      const productName = normalizeCategoryName(product.category_name);
      return [category.name, ...category.aliases].some(name => normalizeCategoryName(name) === productName);
    }) || {
      name: product.category_name || 'Other',
      slug: `category-${product.category_id}`,
      image_url: null
    };
  }

  function serviceIcon(name) {
    const icons = {
      pickup: '<path d="M3 10h18v10H3V10Z"/><path d="M5 10 7 4h10l2 6M8 20v-6h8v6"/><path d="M10 7h4"/>',
      delivery: '<path d="M3 6h11v11H3V6Zm11 4h4l3 4v3h-7"/><circle cx="7" cy="19" r="1.5"/><circle cx="17" cy="19" r="1.5"/>',
      pharmacist: '<path d="M12 3 19 6v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3Z"/><path d="M9 12h6m-3-3v6"/>',
      hours: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'
    };
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name]}</svg>`;
  }

  function productArt(product, extraClass) {
    if (product.image_url) {
      return `<div class="product-art product-art--recorded ${extraClass || ''}"><img src="${escapeHtml(product.image_url)}" alt="${escapeHtml(product.name)}" loading="lazy"></div>`;
    }
    const category = categoryFor(product);
    if (category.image_url) {
      return `
        <div class="product-art product-art--category ${extraClass || ''}">
          <img src="${escapeHtml(category.image_url)}" alt="" loading="lazy">
          <span class="product-art-caption">Category illustration · not a product photo</span>
        </div>`;
    }
    return `
      <div class="product-art product-art--missing ${extraClass || ''}">
        <span>Product photo not supplied by store</span>
      </div>`;
  }

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add('is-visible');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), 2800);
  }

  function applyTheme() {
    document.documentElement.dataset.theme = state.theme;
    document.querySelector('meta[name="theme-color"]').setAttribute('content', state.theme === 'dark' ? '#101b19' : '#f5f4ec');
    document.getElementById('themeLabel').textContent = state.theme === 'dark' ? 'Dark' : 'Light';
    themeToggle.setAttribute('aria-label', `Switch to ${state.theme === 'dark' ? 'light' : 'dark'} theme`);
    themeToggle.querySelector('.theme-icon').textContent = state.theme === 'dark' ? '☾' : '☼';
  }

  function setTheme(theme) {
    state.theme = theme;
    localStorage.setItem('promed-store-theme', theme);
    applyTheme();
  }

  function categoryCards() {
    return categories.filter(category => category.image_url).map(category => {
      return `
      <a class="category-card" href="#/shop?category=${encodeURIComponent(category.slug)}" style="--category-tint:${category.tint};--category-ink:${category.ink}">
        <span class="category-photo"><img src="${escapeHtml(category.image_url)}" alt="" loading="lazy"><small>Category illustration</small></span>
        <span class="category-copy"><strong>${escapeHtml(category.name)}</strong><small>${escapeHtml(category.description)}</small></span>
        <span class="category-arrow" aria-hidden="true">→</span>
      </a>`;
    }).join('');
  }

  function productCard(product) {
    const category = categoryFor(product) || { name: product.category_name };
    const available = product.availability_status === 'available' && product.available_quantity > 0;
    return `
      <article class="product-card">
        ${productArt(product)}
        <div class="product-card-body">
          <span class="product-category">${escapeHtml(category.name)}</span>
          <h3>${escapeHtml(product.name)}</h3>
          <p class="product-brand">${escapeHtml(product.manufacturer || 'Manufacturer not recorded')}</p>
          <span class="availability-label ${available ? 'is-available' : 'is-unavailable'}">${available ? `Available · ${product.available_quantity} eligible` : 'Currently unavailable'}${product.requires_prescription ? ' · pharmacist review required' : ''}</span>
          ${product.requires_prescription ? '<span class="prescription-required-label">Prescription required · pharmacist review</span>' : ''}
          <div class="product-price-row"><span class="product-price">${money(product.unit_price)}</span></div>
          <div class="product-card-actions">
            <a class="button button-secondary button-small" href="#/product/${encodeURIComponent(product.id)}">View details</a>
            <button class="button button-primary button-small" type="button" data-action="add-to-basket" data-product-id="${escapeHtml(product.id)}" ${available ? '' : 'disabled'}>
              ${available ? 'Add to basket' : 'Unavailable'}
            </button>
          </div>
        </div>
      </article>`;
  }

  function sampleNotice() {
    const errors = [state.catalogError, state.catalogMetadataError, state.catalogStatusError].filter(Boolean);
    return `
      <div class="sample-banner" role="note">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/></svg>
        <span><strong>PROMED catalog</strong>${errors.length
          ? `Catalog information could not be fully refreshed: ${escapeHtml(errors.join('; '))}`
          : 'Prices and eligible stock are read from PROMED records. Category photography is illustrative, not a product photo. Stock is rechecked at checkout; an order request does not reserve or deduct stock.'}</span>
      </div>`;
  }

  function catalogEmptyState() {
    if (state.catalogError) {
      return `<div class="empty-state"><div><strong>Product records could not be loaded.</strong><p>${escapeHtml(state.catalogError)}</p><p>Please try again after the PROMED catalog service is available.</p></div></div>`;
    }
    if (state.catalogStatusError) {
      return `<div class="empty-state"><div><strong>Catalog availability could not be verified.</strong><p>${escapeHtml(state.catalogStatusError)}</p><p>No sample products are shown as a fallback.</p></div></div>`;
    }
    if (state.catalogStatus && state.catalogStatus.active_product_count === 0) {
      return `
        <div class="empty-state">
          <div class="empty-state-copy">
            <strong>No active products are configured in the PROMED database.</strong>
            <p>Current records: ${state.catalogStatus.active_product_count} active products, ${state.catalogStatus.category_record_count} configured product categories, and ${state.catalogStatus.eligible_product_count} products with eligible stock. The nine categories above are storefront navigation only; they are not inventory records.</p>
            <p>Staff can sign in to the existing dashboard, create and activate a product, assign its category and selling price, then receive stock into an active batch with a future expiry date. No sample products were added.</p>
            <a class="button button-secondary button-small" href="./index.html">Staff sign in</a>
          </div>
        </div>`;
    }
    if (state.catalogStatus &&
      state.catalogStatus.active_product_count > 0 &&
      state.catalogStatus.eligible_product_count === 0) {
      return `
        <div class="empty-state">
          <div class="empty-state-copy">
            <strong>Active products exist, but none has eligible stock.</strong>
            <p>Check that staff have received a positive quantity into an active batch with an expiry date of today or later. Expired, quarantined and damaged batches are excluded from customer availability.</p>
            <a class="button button-secondary button-small" href="./index.html">Staff sign in</a>
          </div>
        </div>`;
    }
    return '<div class="empty-state"><div><strong>No products match those filters.</strong><p>Try a different search or category.</p></div></div>';
  }

  function renderHome() {
    const featuredProducts = products
      .filter(product => product.availability_status === 'available' && product.available_quantity > 0)
      .slice(0, 4);
    return `
      <section class="hero">
        <div class="content-wrap hero-inner">
          <div class="hero-copy">
            <p class="eyebrow"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2"/></svg>Hospital District · Bengaluru</p>
            <h1>Care essentials,<em>close to home.</em></h1>
            <p class="hero-description">Browse healthcare products recorded by the PROMED neighbourhood store. Availability is checked against eligible, unexpired stock.</p>
            <div class="hero-buttons">
              <a class="button button-primary" href="#/shop">Browse products <span aria-hidden="true">→</span></a>
              <a class="button button-secondary" href="#/track">Track an order <span aria-hidden="true">◇</span></a>
            </div>
            <p class="verified-note"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 19 6v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3Z"/><path d="m9 12 2 2 4-4"/></svg>Product label details are identified as verified only when approved in the store records.</p>
          </div>
          <div class="hero-visual">
            <img class="hero-photo" src="./assets/customer-store-hero.webp" alt="Pharmacy interior shown for storefront design preview">
            <span class="hero-image-label">Storefront image · preview</span>
            <span class="hero-service-label">${serviceIcon('pickup')}Pickup &amp; delivery requests require staff confirmation</span>
          </div>
        </div>
      </section>

      <section class="services-strip" aria-label="Store services">
        <div class="content-wrap services-grid">
          <div class="service-item"><span class="service-icon">${serviceIcon('pickup')}</span><span class="service-copy"><strong>Store pickup</strong><small>Order request · staff confirmation</small></span></div>
          <div class="service-item"><span class="service-icon">${serviceIcon('delivery')}</span><span class="service-copy"><strong>Home delivery</strong><small>Order request · staff confirmation</small></span></div>
          <div class="service-item"><span class="service-icon">${serviceIcon('pharmacist')}</span><span class="service-copy"><strong>Pharmacist review</strong><small>Required items await staff review</small></span></div>
          <div class="service-item"><span class="service-icon">${serviceIcon('hours')}</span><span class="service-copy"><strong>Store hours</strong><small>Not configured</small></span></div>
        </div>
      </section>

      <section class="section">
        <div class="content-wrap">
          <div class="section-heading">
            <div><p class="eyebrow">Browse by category</p><h2>Find your essentials</h2><p>Nine customer-facing categories, even when a category has no listed products.</p></div>
            <a class="text-link" href="#/shop">View all categories <span aria-hidden="true">→</span></a>
          </div>
          <div class="category-grid">${categoryCards()}</div>
        </div>
      </section>

      <section class="section section-muted">
        <div class="content-wrap">
          <div class="section-heading">
            <div><p class="eyebrow">Current catalog</p><h2>Products for browsing</h2><p>Product facts are shown only when recorded; unverified information is identified.</p></div>
            <a class="text-link" href="#/shop">Explore the shop <span aria-hidden="true">→</span></a>
          </div>
          <div class="product-grid">${featuredProducts.length ? featuredProducts.map(productCard).join('') : catalogEmptyState()}</div>
        </div>
      </section>
      <section class="section"><div class="content-wrap">${sampleNotice()}</div></section>`;
  }

  function renderPageHeading(eyebrow, title, description) {
    return `
      <section class="page-hero"><div class="content-wrap page-heading">
        <p class="eyebrow">${escapeHtml(eyebrow)}</p><h1>${escapeHtml(title)}</h1><p>${escapeHtml(description)}</p>
      </div></section>`;
  }

  function renderShop() {
    return `
      ${renderPageHeading('Store catalog', 'Shop healthcare essentials', 'Search current product records and review their recorded availability.')}
      <section class="page-body"><div class="content-wrap">
        ${sampleNotice()}
        <div class="shop-toolbar" aria-label="Product filters">
          <label>Search products<input id="shopSearch" type="search" value="${escapeHtml(state.shopSearch)}" placeholder="Search name, category, or barcode"></label>
          <label>Category<select id="shopCategory">
            <option value="all">All categories</option>
            ${categories.map(category => `<option value="${escapeHtml(category.slug)}" ${state.shopCategory === category.slug ? 'selected' : ''}>${escapeHtml(category.name)}</option>`).join('')}
          </select></label>
          <label>Availability<select id="shopAvailability">
            <option value="all" ${state.shopAvailability === 'all' ? 'selected' : ''}>All products</option>
            <option value="available" ${state.shopAvailability === 'available' ? 'selected' : ''}>Available</option>
            <option value="unavailable" ${state.shopAvailability === 'unavailable' ? 'selected' : ''}>Unavailable</option>
          </select></label>
          <label>Sort by<select id="shopSort">
            <option value="name-asc" ${state.shopSort === 'name-asc' ? 'selected' : ''}>Name: A to Z</option>
            <option value="name-desc" ${state.shopSort === 'name-desc' ? 'selected' : ''}>Name: Z to A</option>
            <option value="price-asc" ${state.shopSort === 'price-asc' ? 'selected' : ''}>Price: low to high</option>
            <option value="price-desc" ${state.shopSort === 'price-desc' ? 'selected' : ''}>Price: high to low</option>
          </select></label>
        </div>
        <div class="results-meta"><span id="resultsCount" aria-live="polite"></span><span>Prices shown in INR · database records</span></div>
        <p class="form-status" id="catalogStatus" role="status" aria-live="polite"></p>
        <div class="product-grid" id="shopProductGrid"></div>
        <p class="verified-note"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 19 6v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3Z"/><path d="m9 12 2 2 4-4"/></svg>Availability is revalidated at checkout. Verified product details are explicitly marked on each record.</p>
      </div></section>`;
  }

  function filteredProducts() {
    const visibleProducts = products.filter(product => {
      const matchesCategory = state.shopCategory === 'all' || categoryFor(product).slug === state.shopCategory;
      const matchesAvailability = state.shopAvailability === 'all' ||
        (state.shopAvailability === 'available' && product.availability_status === 'available') ||
        (state.shopAvailability === 'unavailable' && product.availability_status !== 'available');
      return matchesCategory && matchesAvailability;
    });

    if (state.shopSort === 'name-asc') visibleProducts.sort((first, second) => first.name.localeCompare(second.name));
    if (state.shopSort === 'name-desc') visibleProducts.sort((first, second) => second.name.localeCompare(first.name));
    if (state.shopSort === 'price-asc') visibleProducts.sort((first, second) => first.unit_price - second.unit_price);
    if (state.shopSort === 'price-desc') visibleProducts.sort((first, second) => second.unit_price - first.unit_price);
    return visibleProducts;
  }

  function updateShopResults() {
    const grid = document.getElementById('shopProductGrid');
    if (!grid) return;
    const found = filteredProducts();
    document.getElementById('resultsCount').textContent = `${found.length} ${found.length === 1 ? 'product' : 'products'}`;
    grid.innerHTML = found.length ? found.map(productCard).join('') : catalogEmptyState();
    const status = document.getElementById('catalogStatus');
    status.textContent = state.catalogError;
    status.classList.toggle('is-error', Boolean(state.catalogError));
  }

  function renderProductDetail(productId) {
    const product = productCache.get(String(productId)) ||
      products.find(item => String(item.id) === String(productId));
    if (!product) {
      return `${renderPageHeading('Store catalog', 'Product not found', 'This product is not available in the current catalog response.')}
        <section class="page-body"><div class="content-wrap"><a class="button button-primary" href="#/shop">Return to shop</a></div></section>`;
    }
    const category = categoryFor(product) || { name: product.category_name };
    const verified = product.product_information_verified;
    const available = product.availability_status === 'available' && product.available_quantity > 0;
    const infoValue = field => verified && product[field]
      ? escapeHtml(product[field])
      : 'Not available as verified product information.';
    const prescriptionText = product.requires_prescription
      ? 'This product requires pharmacist review before the order can be accepted. Prescription documents are not collected through this storefront.'
      : 'The product record is not marked as prescription-required. Confirm prescription requirements with a pharmacist.';
    return `
      ${renderPageHeading('Product details', category.name, 'Product information is displayed from PROMED records.')}
      <section class="page-body"><div class="content-wrap">
        ${sampleNotice()}
        <div class="detail-layout" style="margin-top:24px">
          <div class="detail-image">${productArt(product)}</div>
          <div class="detail-copy">
            <p class="eyebrow">${escapeHtml(category.name)}</p>
            <h1>${escapeHtml(product.name)}</h1>
            <p class="detail-maker">Manufacturer / company: ${escapeHtml(product.manufacturer || 'Not recorded')}</p>
            <p class="detail-price">${money(product.unit_price)}</p>
            <p class="detail-disclaimer">Price from current product record · stock may change before review</p>
            <div class="info-tile"><strong>Availability</strong><span>${available ? `${product.available_quantity} eligible units currently available` : 'Currently unavailable'}</span></div>
            <div class="detail-info-grid">
              <div class="info-tile"><strong>Ingredients &amp; strengths</strong><span>${infoValue('ingredients_strengths')}</span></div>
              <div class="info-tile"><strong>Common uses</strong><span>${infoValue('common_uses')}</span></div>
            </div>
            <div class="prescription-notice"><strong>${product.requires_prescription ? 'Pharmacist review required' : 'Prescription status from store record'}</strong>${escapeHtml(prescriptionText)}</div>
            <p class="detail-disclaimer">${verified ? 'Product details marked pharmacist-verified in the store record.' : 'Product details have not been marked pharmacist-verified.'}</p>
            ${product.description ? `<div class="detail-section"><h2>Product description</h2><p>${infoValue('description')}</p></div>` : ''}
            <div class="detail-section"><h2>Directions for use</h2><p>${infoValue('directions')}</p></div>
            <div class="detail-section"><h2>Warnings and precautions</h2><p>${infoValue('warnings')}</p></div>
            <div class="button-row" style="margin-top:18px">
              <button class="button button-primary" type="button" data-action="add-to-basket" data-product-id="${escapeHtml(product.id)}" ${available ? '' : 'disabled'}>${available ? 'Add to basket' : 'Unavailable'}</button>
              <a class="button button-secondary" href="#/shop?category=${encodeURIComponent(category.slug)}">Back to category</a>
            </div>
          </div>
        </div>
      </div></section>`;
  }

  function cartEntries() {
    return Object.entries(state.cart)
      .map(([id, quantity]) => ({ product: productCache.get(String(id)), quantity }))
      .filter(entry => entry.product);
  }

  function basketCount() {
    return cartEntries().reduce((total, entry) => total + entry.quantity, 0);
  }

  function basketSubtotal() {
    return cartEntries().reduce((total, entry) => total + Number(entry.product.unit_price) * entry.quantity, 0);
  }

  function basketRows() {
    return cartEntries().map(({ product, quantity }) => `
      <article class="basket-row">
        <div class="basket-thumb">${productArt(product)}</div>
        <div class="basket-product"><h3>${escapeHtml(product.name)}</h3><p>${money(product.unit_price)} · current listed price</p><p>${product.availability_status === 'available' ? `${product.available_quantity} eligible units currently available` : 'Currently unavailable'} · no stock is reserved.</p></div>
        <div class="basket-row-actions">
          <div class="quantity-control" aria-label="Quantity for ${escapeHtml(product.name)}">
            <button type="button" data-action="decrease-quantity" data-product-id="${escapeHtml(product.id)}" aria-label="Decrease quantity">−</button>
            <span>${quantity}</span>
            <button type="button" data-action="increase-quantity" data-product-id="${escapeHtml(product.id)}" aria-label="Increase quantity" ${quantity >= product.available_quantity ? 'disabled' : ''}>+</button>
          </div>
          <span class="basket-line-price">${money(product.unit_price * quantity)}</span>
          <button class="remove-button" type="button" data-action="remove-from-basket" data-product-id="${escapeHtml(product.id)}">Remove</button>
        </div>
      </article>`).join('');
  }

  function summaryPanel(checkout) {
    const total = money(basketSubtotal());
    return `
      <aside class="panel summary-panel">
        <h2>Order summary</h2>
        ${checkout ? `<div class="summary-items">${cartEntries().map(({ product, quantity }) => `<div class="summary-item"><span>${escapeHtml(product.name)} × ${quantity}</span><strong>${money(product.unit_price * quantity)}</strong></div>`).join('')}</div>` : ''}
        <div class="summary-line"><span>Subtotal</span><strong>${total}</strong></div>
        <div class="summary-line"><span>Tax</span><span>Not configured</span></div>
        <div class="summary-line"><span>Delivery / pickup</span><span>Confirmed by staff</span></div>
        <div class="summary-line total"><span>Estimated total</span><strong>${total}</strong></div>
        <p class="summary-note">Prices are from product records. Tax and delivery charges are not configured. Payment is not collected here.</p>
        ${checkout
          ? '<a class="button button-secondary" href="#/basket">Back to basket</a>'
          : '<a class="button button-primary" href="#/checkout">Proceed to checkout</a>'}
        <a class="button button-secondary" href="#/shop">Continue shopping</a>
      </aside>`;
  }

  function renderBasket() {
    const entries = cartEntries();
    return `
      ${renderPageHeading('Your basket', 'Your basket', 'Review current product prices and quantities. Stock is not reserved while items are in the basket.')}
      <section class="page-body"><div class="content-wrap">
        ${sampleNotice()}
        ${entries.length
          ? `<div class="basket-layout" style="margin-top:22px"><section class="panel basket-list" aria-label="Basket products">${basketRows()}</section>${summaryPanel(false)}</div>`
          : `<div class="empty-state" style="margin-top:22px">Your basket is empty.<br><a class="text-link" href="#/shop">Browse products <span aria-hidden="true">→</span></a></div>`}
      </div></section>`;
  }

  function renderCheckout() {
    const entries = cartEntries();
    if (!entries.length) {
      return `
        ${renderPageHeading('Checkout', 'Your basket is empty', 'Add products to review an order request.')}
        <section class="page-body"><div class="content-wrap">${sampleNotice()}<div class="button-row" style="margin-top:20px"><a class="button button-primary" href="#/shop">Browse products</a></div></div></section>`;
    }
    if (!state.customer) {
      return `
        ${renderPageHeading('Checkout', 'Sign in to continue', 'A customer account is required to submit and track an order.')}
        <section class="page-body"><div class="content-wrap">${sampleNotice()}<div class="panel track-search-panel" style="margin-top:22px"><p>Please sign in or create an account. Your basket contains only product IDs and quantities on this browser.</p><a class="button button-primary" href="#/account">Go to customer account</a></div></div></section>`;
    }
    return `
      ${renderPageHeading('Checkout', 'Fulfilment details', 'Submit an order request for staff review. No payment is collected and no stock is reserved.')}
      <section class="page-body"><div class="content-wrap">
        ${sampleNotice()}
        <div class="checkout-layout" style="margin-top:22px">
          <form class="panel checkout-form" id="checkoutForm">
            <h2>Customer details</h2>
            <p class="form-status">Order contact: ${escapeHtml(state.customer.display_name)} · ${escapeHtml(state.customer.phone || 'Add a phone number to your account')}</p>
            <fieldset style="border:0;padding:0;margin:0">
              <legend class="field" style="margin-bottom:8px">Choose fulfilment</legend>
              <div class="fulfilment-options">
                <label class="fulfilment-option"><input type="radio" name="fulfillment_method" value="pickup" ${state.fulfillment === 'pickup' ? 'checked' : ''}><span><strong>Store pickup</strong><small>Staff confirmation required</small></span></label>
                <label class="fulfilment-option"><input type="radio" name="fulfillment_method" value="delivery" ${state.fulfillment === 'delivery' ? 'checked' : ''}><span><strong>Home delivery</strong><small>Staff confirmation required</small></span></label>
              </div>
            </fieldset>
            <label class="field" id="deliveryAddressField" ${state.fulfillment === 'delivery' ? '' : 'hidden'}>Delivery address<textarea name="delivery_address" maxlength="320" autocomplete="street-address" ${state.fulfillment === 'delivery' ? 'required' : ''}></textarea></label>
            <p class="form-status" id="checkoutStatus" role="status" aria-live="polite"></p>
            <button class="button button-primary" type="submit">Submit order request</button>
          </form>
          ${summaryPanel(true)}
        </div>
      </div></section>`;
  }

  function statusLabel(status) {
    return ({
      RECEIVED: 'Received',
      PHARMACIST_REVIEW: 'Pharmacist Review',
      ACCEPTED: 'Accepted',
      PREPARING: 'Preparing',
      READY_FOR_PICKUP: 'Ready for Pickup',
      OUT_FOR_DELIVERY: 'Out for Delivery',
      COMPLETED: 'Completed',
      REJECTED: 'Rejected',
      CANCELLED: 'Cancelled'
    })[status] || status;
  }

  function renderTrackResult(order) {
    const timeline = order.status_timeline.map((event, index) => `
      <div class="timeline-step ${index === order.status_timeline.length - 1 ? 'is-current' : 'is-complete'}">
        <span class="timeline-dot" aria-hidden="true"></span><span>${escapeHtml(statusLabel(event.status))} · ${escapeHtml(event.created_at)}</span>
      </div>`).join('');
    return `
      <section class="panel track-result" aria-live="polite">
        <div class="track-result-head"><div><h2>Order ${escapeHtml(order.order_number)}</h2><p>${escapeHtml(order.created_at)} · ${escapeHtml(order.fulfillment_method)}</p></div><span class="preview-pill">${escapeHtml(statusLabel(order.status))}</span></div>
        <p>${order.items.map(item => `${escapeHtml(item.product_name)} × ${item.quantity}`).join('<br>')}</p>
        <p><strong>Total: ${money(order.total_amount)}</strong></p>
        ${order.requires_pharmacist_review ? '<p class="prescription-notice">This order includes a prescription-required item and awaits pharmacist review. Prescription documents are not submitted through this site.</p>' : ''}
        <div class="timeline">${timeline}</div>
      </section>`;
  }

  function renderTrack() {
    return `
      ${renderPageHeading('Order updates', 'Track an order', 'Look up an order associated with your signed-in account.')}
      <section class="page-body"><div class="content-wrap">
        ${sampleNotice()}
        <div class="panel track-search-panel" style="margin-top:22px">
          <h2>Enter an order reference</h2>
          ${state.customer ? `<form class="track-form" id="trackForm">
            <label class="field">Order reference<input name="orderReference" maxlength="40" value="${escapeHtml(trackReference)}" placeholder="e.g. WEB-123ABC" required></label>
            <button class="button button-primary" type="submit">Track order</button>
          </form>` : '<p><a class="text-link" href="#/account">Sign in to track your orders.</a></p>'}
          <p class="form-status" id="trackStatus" role="status" aria-live="polite"></p>
        </div>
        <div id="trackResult">${state.trackResult ? renderTrackResult(state.trackResult) : ''}</div>
      </div></section>`;
  }

  function renderAccount() {
    if (!state.customer) {
      return `
        ${renderPageHeading('Customer account', 'Sign in or create an account', 'Your account protects access to your order history.')}
        <section class="page-body"><div class="content-wrap">
          ${sampleNotice()}
          <div class="account-layout" style="margin-top:22px">
            <section class="panel account-card">
              <h2>Sign in</h2>
              <form class="stacked-form" id="customerLoginForm">
                <label class="field">Email<input name="email" type="email" maxlength="254" autocomplete="username" required></label>
                <label class="field">Password<input name="password" type="password" maxlength="128" autocomplete="current-password" required></label>
                <p class="form-status ${state.authError ? 'is-error' : ''}" id="customerLoginStatus" role="status" aria-live="polite">${escapeHtml(state.authError)}</p>
                <button class="button button-primary" type="submit">Sign in</button>
              </form>
            </section>
            <section class="panel account-card">
              <h2>Create customer account</h2>
              <form class="stacked-form" id="customerRegisterForm">
                <label class="field">Name<input name="display_name" maxlength="160" autocomplete="name" required></label>
                <label class="field">Email<input name="email" type="email" maxlength="254" autocomplete="email" required></label>
                <label class="field">Phone<input name="phone" type="tel" maxlength="32" autocomplete="tel" required></label>
                <label class="field">Password<input name="password" type="password" minlength="12" maxlength="128" autocomplete="new-password" required><small>Use at least 12 characters.</small></label>
                <p class="form-status ${state.authError ? 'is-error' : ''}" id="customerRegisterStatus" role="status" aria-live="polite">${escapeHtml(state.authError)}</p>
                <button class="button button-primary" type="submit">Create account</button>
              </form>
            </section>
          </div>
        </div></section>`;
    }
    return `
      ${renderPageHeading('Customer account', 'Your PROMED account', 'Manage your profile access and view orders associated with this account.')}
      <section class="page-body"><div class="content-wrap">
        <div class="account-layout" style="margin-top:22px">
          <section class="panel account-card">
            <span class="account-avatar"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M5.5 20v-1.5a6.5 6.5 0 0 1 13 0V20"/></svg></span>
            <h2>${escapeHtml(state.customer.display_name)}</h2>
            <p>${escapeHtml(state.customer.email)}<br>${escapeHtml(state.customer.phone || 'Phone not provided')}</p>
            <button class="button button-secondary" type="button" data-action="customer-logout">Sign out</button>
          </section>
          <section class="panel account-card">
            <h2>My orders</h2>
            ${state.accountOrders.length ? state.accountOrders.map(order => `<div class="account-order-card"><span><strong>${escapeHtml(order.order_number)}</strong><small>${escapeHtml(statusLabel(order.status))} · ${money(order.total_amount)}</small></span><a class="text-link" href="#/track" data-track-order="${escapeHtml(order.order_number)}">Track <span aria-hidden="true">→</span></a></div>`).join('') : '<p>No orders have been placed on this account.</p>'}
          </section>
        </div>
      </div></section>`;
  }

  function currentRoute() {
    const fragment = window.location.hash.slice(1) || '/home';
    const splitAt = fragment.indexOf('?');
    const path = splitAt < 0 ? fragment : fragment.slice(0, splitAt);
    const params = new URLSearchParams(splitAt < 0 ? '' : fragment.slice(splitAt + 1));
    return { path: path.startsWith('/') ? path : `/${path}`, params };
  }

  async function loadProducts() {
    const fullCatalog = !state.shopSearch.trim() &&
      state.shopCategory === 'all' &&
      state.shopAvailability === 'all';
    const params = new URLSearchParams();
    if (state.shopSearch.trim()) params.set('q', state.shopSearch.trim());
    if (state.shopCategory !== 'all') params.set('category', state.shopCategory);
    if (state.shopAvailability !== 'all') params.set('available', String(state.shopAvailability === 'available'));
    params.set('sort', state.shopSort);
    try {
      products = await PromedApi.get(`/store/catalog/products?${params.toString()}`);
      if (fullCatalog) productCache.clear();
      products.forEach(product => productCache.set(String(product.id), product));
      if (fullCatalog) {
        let changed = false;
        Object.keys(state.cart).forEach(id => {
          if (!productCache.has(String(id))) {
            delete state.cart[id];
            changed = true;
          }
        });
        if (changed) saveCart();
      }
      state.catalogError = '';
    } catch (error) {
      products = [];
      state.catalogError = error.message;
    }
  }

  function setStoreCategories(response) {
    const apiCategories = Array.isArray(response) ? response : [];
    const apiCategoriesBySlug = new Map(apiCategories.map(category => [category.slug, category]));
    categories = categoryDefinitions.map(definition => {
      const apiCategory = apiCategoriesBySlug.get(definition.slug);
      return {
        ...definition,
        id: apiCategory?.id ?? null,
        database_category_ids: apiCategory?.database_category_ids ||
          (apiCategory?.id ? [apiCategory.id] : [])
      };
    });
    categories.push(...apiCategories
      .filter(category => !categoryDefinitions.some(definition => definition.slug === category.slug))
      .map(category => ({
        ...category,
        image_url: null,
        aliases: [],
        tint: '#e5f1ed',
        ink: '#25836d',
        database_category_ids: category.database_category_ids || [category.id]
      })));
  }

  async function loadStoreData() {
    const route = currentRoute();
    if (route.path === '/shop') {
      state.shopSearch = route.params.get('q') || '';
      state.shopCategory = route.params.get('category') || 'all';
    }
    state.catalogError = '';
    state.catalogMetadataError = '';
    state.catalogStatusError = '';
    try {
      const categoriesResponse = await PromedApi.get('/store/catalog/categories');
      setStoreCategories(categoriesResponse);
    } catch (error) {
      state.catalogMetadataError = error.message;
    }
    try {
      state.catalogStatus = await PromedApi.get('/store/catalog/status');
    } catch (error) {
      state.catalogStatus = null;
      state.catalogStatusError = error.message;
    }
    await loadProducts();
    try {
      state.customer = await PromedApi.get('/auth/customer/me');
      state.accountOrders = state.customer
        ? await PromedApi.get('/customer/orders')
        : [];
    } catch (error) {
      if (!/sign in|session is invalid or expired/i.test(error.message)) state.authError = error.message;
      state.customer = null;
      state.accountOrders = [];
    }
    render();
  }

  async function reloadAccountOrders() {
    if (!state.customer) {
      state.accountOrders = [];
      return;
    }
    state.accountOrders = await PromedApi.get('/customer/orders');
  }

  function updateBasketCount() {
    const count = basketCount();
    document.getElementById('basketCount').textContent = count;
    document.getElementById('basketCount').setAttribute('aria-label', `${count} items in basket`);
  }

  function render() {
    const route = currentRoute();
    const productRoute = route.path.match(/^\/product\/([^/]+)$/);
    if (route.path === '/home') storeContent.innerHTML = renderHome();
    else if (route.path === '/shop') storeContent.innerHTML = renderShop();
    else if (productRoute) storeContent.innerHTML = renderProductDetail(decodeURIComponent(productRoute[1]));
    else if (route.path === '/basket') storeContent.innerHTML = renderBasket();
    else if (route.path === '/checkout') storeContent.innerHTML = renderCheckout();
    else if (route.path === '/track') storeContent.innerHTML = renderTrack();
    else if (route.path === '/account') storeContent.innerHTML = renderAccount();
    else storeContent.innerHTML = renderHome();

    document.querySelectorAll('[data-nav]').forEach(link => {
      link.classList.toggle('active', link.dataset.nav === route.path.slice(1));
    });
    document.getElementById('headerSearchInput').value = route.path === '/shop' ? state.shopSearch : '';
    updateBasketCount();
    if (route.path === '/shop') updateShopResults();
    applyTheme();
  }

  function navigate(path) {
    if (window.location.hash === `#${path}`) {
      handleRouteChange();
    } else {
      window.location.hash = path;
    }
  }

  function handleRouteChange() {
    const route = currentRoute();
    if (route.path === '/shop') {
      state.shopSearch = route.params.get('q') || '';
      state.shopCategory = route.params.get('category') || 'all';
      loadProducts().then(render);
      return;
    }
    if (route.path !== '/home') {
      state.shopSearch = '';
      state.shopCategory = 'all';
      state.shopAvailability = 'all';
      loadProducts().then(render);
      return;
    }
    loadProducts().then(render);
  }

  function addToBasket(id) {
    const product = productCache.get(String(id));
    if (!product || product.availability_status !== 'available' || product.available_quantity < 1) {
      showToast('This product is currently unavailable.');
      return;
    }
    const quantity = state.cart[id] || 0;
    if (quantity >= Math.min(99, product.available_quantity)) {
      showToast('The basket quantity cannot exceed eligible stock.');
      return;
    }
    state.cart[id] = quantity + 1;
    saveCart();
    updateBasketCount();
    showToast('Added to your basket. No stock was reserved.');
  }

  function changeQuantity(id, amount) {
    const current = state.cart[id] || 0;
    const next = current + amount;
    const product = productCache.get(String(id));
    if (next <= 0) delete state.cart[id];
    else if (product && next <= Math.min(99, product.available_quantity)) state.cart[id] = next;
    else {
      showToast('The basket quantity cannot exceed currently eligible stock.');
      return;
    }
    saveCart();
    render();
  }

  async function renderTrackStatus(reference) {
    const result = document.getElementById('trackResult');
    const status = document.getElementById('trackStatus');
    trackReference = reference.trim();
    status.textContent = 'Looking up your order...';
    result.replaceChildren();
    try {
      state.trackResult = await PromedApi.get(
        `/customer/orders/by-number/${encodeURIComponent(trackReference)}`
      );
      status.textContent = '';
      result.innerHTML = renderTrackResult(state.trackResult);
    } catch (error) {
      state.trackResult = null;
      status.textContent = error.message;
      status.classList.add('is-error');
    }
  }

  async function handleAccountForm(form) {
    const fields = new FormData(form);
    const register = form.id === 'customerRegisterForm';
    const status = document.getElementById(register ? 'customerRegisterStatus' : 'customerLoginStatus');
    const body = Object.fromEntries(fields.entries());
    status.textContent = register ? 'Creating account...' : 'Signing in...';
    status.classList.remove('is-error');
    try {
      state.customer = await PromedApi.post(
        register ? '/auth/customer/register' : '/auth/customer/login',
        body
      );
      state.authError = '';
      await reloadAccountOrders();
      render();
      showToast(register ? 'Your customer account is ready.' : 'You are signed in.');
    } catch (error) {
      status.textContent = error.message;
      status.classList.add('is-error');
    }
  }

  document.addEventListener('click', async event => {
    const navLink = event.target.closest('[data-nav]');
    if (navLink) {
      navigation.classList.remove('is-open');
      menuToggle.setAttribute('aria-expanded', 'false');
    }

    const trackedOrder = event.target.closest('[data-track-order]');
    if (trackedOrder) {
      event.preventDefault();
      trackReference = trackedOrder.dataset.trackOrder;
      try {
        state.trackResult = await PromedApi.get(
          `/customer/orders/by-number/${encodeURIComponent(trackReference)}`
        );
        navigate('/track');
      } catch (error) {
        showToast(error.message);
      }
      return;
    }

    const action = event.target.closest('[data-action]');
    if (!action) return;
    const id = action.dataset.productId;
    if (action.dataset.action === 'add-to-basket') addToBasket(id);
    if (action.dataset.action === 'increase-quantity') changeQuantity(id, 1);
    if (action.dataset.action === 'decrease-quantity') changeQuantity(id, -1);
    if (action.dataset.action === 'remove-from-basket') {
      delete state.cart[id];
      saveCart();
      render();
      showToast('Removed from your basket.');
    }
    if (action.dataset.action === 'customer-logout') {
      try {
        await PromedApi.post('/auth/customer/logout', {});
        state.customer = null;
        state.accountOrders = [];
        state.trackResult = null;
        render();
      } catch (error) {
        showToast(error.message);
      }
    }
  });

  document.addEventListener('input', event => {
    if (event.target.id === 'shopSearch') {
      state.shopSearch = event.target.value;
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(async () => {
        await loadProducts();
        render();
      }, 250);
    }
  });

  document.addEventListener('change', async event => {
    if (event.target.id === 'shopCategory') state.shopCategory = event.target.value;
    if (event.target.id === 'shopAvailability') state.shopAvailability = event.target.value;
    if (event.target.id === 'shopSort') state.shopSort = event.target.value;
    if (['shopCategory', 'shopAvailability', 'shopSort'].includes(event.target.id)) {
      await loadProducts();
      render();
    }

    if (event.target.name === 'fulfillment_method') {
      state.fulfillment = event.target.value;
      const addressField = document.getElementById('deliveryAddressField');
      const addressInput = addressField.querySelector('textarea');
      const deliverySelected = state.fulfillment === 'delivery';
      addressField.hidden = !deliverySelected;
      addressInput.required = deliverySelected;
    }
  });

  document.addEventListener('submit', async event => {
    if (event.target.id === 'headerSearch') {
      event.preventDefault();
      const query = new FormData(event.target).get('q').trim();
      state.shopSearch = query;
      navigate(`/shop?q=${encodeURIComponent(query)}`);
    }

    if (event.target.id === 'customerLoginForm' || event.target.id === 'customerRegisterForm') {
      event.preventDefault();
      await handleAccountForm(event.target);
    }

    if (event.target.id === 'checkoutForm') {
      event.preventDefault();
      const status = document.getElementById('checkoutStatus');
      const fields = new FormData(event.target);
      const items = cartEntries().map(entry => ({
        product_id: entry.product.id,
        quantity: entry.quantity
      }));
      if (!checkoutKey) {
        checkoutKey = window.crypto?.randomUUID
          ? window.crypto.randomUUID()
          : `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      }
      status.textContent = 'Rechecking stock and submitting your order...';
      status.classList.remove('is-error');
      try {
        const order = await PromedApi.post('/customer/orders', {
          items,
          fulfillment_method: fields.get('fulfillment_method'),
          delivery_address: fields.get('delivery_address') || null,
          idempotency_key: checkoutKey
        });
        checkoutKey = null;
        state.cart = {};
        saveCart();
        state.trackResult = order;
        trackReference = order.order_number;
        await reloadAccountOrders();
        navigate('/track');
      } catch (error) {
        status.textContent = error.message;
        status.classList.add('is-error');
      }
    }

    if (event.target.id === 'trackForm') {
      event.preventDefault();
      await renderTrackStatus(new FormData(event.target).get('orderReference'));
    }
  });

  themeToggle.addEventListener('click', () => setTheme(state.theme === 'dark' ? 'light' : 'dark'));

  menuToggle.addEventListener('click', () => {
    const isOpen = navigation.classList.toggle('is-open');
    menuToggle.setAttribute('aria-expanded', String(isOpen));
    menuToggle.setAttribute('aria-label', isOpen ? 'Close customer store menu' : 'Open customer store menu');
  });

  window.addEventListener('hashchange', handleRouteChange);
  applyTheme();
  loadStoreData();
})();
