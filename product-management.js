class PromedProductManagement {
  constructor() {
    this.categories = [];
    this.products = [];
    this.editingProductId = null;
    this.editingOriginalCategoryId = null;
    this.searchTimer = null;
    this.previewUrl = null;
    this.form = document.getElementById('managedProductForm');
    this.imageInput = document.getElementById('managedProductImage');
    this.imagePreview = document.getElementById('managedProductImagePreview');
    this.stockToggle = document.getElementById('initialStockToggle');
    this.stockFields = document.getElementById('initialStockFields');
  }

  async init(role) {
    if (role !== 'owner') return;
    document.getElementById('productsNavLink').hidden = false;
    document.getElementById('view-products').hidden = false;
    this.bindEvents();
    const today = new Date();
    this.form.elements.purchase_date.value =
      `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    await Promise.all([this.loadCategories(), this.loadReceiptOptions()]);
    await this.loadProducts();
  }

  bindEvents() {
    this.form.addEventListener('submit', event => {
      event.preventDefault();
      this.saveProduct().catch(error => this.setStatus(error.message, true));
    });

    document.getElementById('refreshManagedProductsBtn').addEventListener('click', () => {
      this.refresh().catch(error => this.setStatus(error.message, true));
    });
    document.getElementById('productsNavLink').addEventListener('click', () => {
      this.refresh().catch(error => this.setStatus(error.message, true));
    });
    document.getElementById('managedProductSearch').addEventListener('input', () => {
      clearTimeout(this.searchTimer);
      this.searchTimer = setTimeout(() => {
        this.loadProducts().catch(error => this.setStatus(error.message, true));
      }, 250);
    });
    document.getElementById('managedProductFilterCategory').addEventListener('change', () => {
      this.loadProducts().catch(error => this.setStatus(error.message, true));
    });
    document.getElementById('managedProductFilterStatus').addEventListener('change', () => {
      this.loadProducts().catch(error => this.setStatus(error.message, true));
    });

    this.stockToggle.addEventListener('change', () => this.updateStockFields());
    this.imageInput.addEventListener('change', () => this.previewSelectedImage());
    document.getElementById('removeManagedProductImageBtn').addEventListener('click', () => {
      this.removeImage().catch(error => this.setStatus(error.message, true));
    });
    document.getElementById('cancelManagedProductEditBtn').addEventListener('click', () => this.resetForm());

    document.getElementById('managedProductsTableBody').addEventListener('click', event => {
      const editButton = event.target.closest('[data-edit-product]');
      const toggleButton = event.target.closest('[data-toggle-product]');
      if (editButton) this.startEditing(Number(editButton.dataset.editProduct));
      if (toggleButton) {
        this.toggleProduct(Number(toggleButton.dataset.toggleProduct), toggleButton.dataset.active === 'true')
          .catch(error => this.setStatus(error.message, true));
      }
    });
    document.getElementById('managedCategoriesTableBody').addEventListener('click', event => {
      const saveButton = event.target.closest('[data-save-category]');
      const toggleButton = event.target.closest('[data-toggle-category]');
      if (saveButton) {
        this.saveCategory(Number(saveButton.dataset.saveCategory))
          .catch(error => this.setStatus(error.message, true));
      }
      if (toggleButton) {
        this.toggleCategory(Number(toggleButton.dataset.toggleCategory), toggleButton.dataset.active === 'true')
          .catch(error => this.setStatus(error.message, true));
      }
    });
    document.getElementById('createManagedCategoryForm').addEventListener('submit', event => {
      event.preventDefault();
      this.createCategory(event.currentTarget).catch(error => this.setStatus(error.message, true));
    });
  }

  async refresh() {
    await this.loadCategories();
    await Promise.all([this.loadReceiptOptions(), this.loadProducts()]);
  }

  async loadCategories() {
    const selectedCategory = document.getElementById('managedProductCategory').value;
    const selectedFilter = document.getElementById('managedProductFilterCategory').value;
    this.categories = await PromedApi.get('/categories');
    const activeOptions = this.categories
      .map(category => `<option value="${category.id}" ${category.active ? '' : 'disabled'}>${this.escape(category.name)}${category.active ? '' : ' (inactive)'}</option>`)
      .join('');
    const allOptions = this.categories
      .map(category => `<option value="${category.id}">${this.escape(category.name)}${category.active ? '' : ' (inactive)'}</option>`)
      .join('');
    document.getElementById('managedProductCategory').innerHTML =
      `<option value="">Select a category</option>${activeOptions}`;
    document.getElementById('managedProductFilterCategory').innerHTML =
      `<option value="">All categories</option>${allOptions}`;
    if (this.categories.some(category => String(category.id) === selectedCategory)) {
      document.getElementById('managedProductCategory').value = selectedCategory;
    }
    if (this.categories.some(category => String(category.id) === selectedFilter)) {
      document.getElementById('managedProductFilterCategory').value = selectedFilter;
    }
    this.renderCategories();
  }

  async loadReceiptOptions() {
    const [locations, suppliers] = await Promise.all([
      PromedApi.get('/locations'),
      PromedApi.get('/suppliers')
    ]);
    document.getElementById('initialStockLocation').innerHTML =
      `<option value="">Select a location</option>${locations.map(location =>
        `<option value="${this.escape(location.code)}">${this.escape(location.code)} · ${this.escape(location.name)}</option>`
      ).join('')}`;
    document.getElementById('initialStockSupplier').innerHTML =
      `<option value="">No supplier recorded</option>${suppliers.map(supplier =>
        `<option value="${supplier.id}">${this.escape(supplier.name)}</option>`
      ).join('')}`;
  }

  async loadProducts() {
    const params = new URLSearchParams();
    const query = document.getElementById('managedProductSearch').value.trim();
    const categoryId = document.getElementById('managedProductFilterCategory').value;
    const active = document.getElementById('managedProductFilterStatus').value;
    if (query) params.set('q', query);
    if (categoryId) params.set('category_id', categoryId);
    if (active) params.set('active', active);
    const suffix = params.toString() ? `?${params}` : '';
    this.products = await PromedApi.get(`/management/products${suffix}`);
    this.renderProducts();
  }

  renderProducts() {
    const body = document.getElementById('managedProductsTableBody');
    if (!this.products.length) {
      body.innerHTML = '<tr><td colspan="8" class="empty-state">No products match these filters. Add a real product record above.</td></tr>';
      return;
    }
    body.innerHTML = this.products.map(product => {
      const batches = product.batches.length
        ? product.batches.map(batch =>
          `${this.escape(batch.batch_number)} · ${batch.quantity} on hand · expires ${this.escape(batch.expiry_date)} · ${this.escape(batch.status)}`
        ).join('<br>')
        : 'No batches recorded';
      const locations = product.location_quantities.length
        ? product.location_quantities.map(item => `${this.escape(item.location_code)}: ${item.quantity}`).join('<br>')
        : 'No locations';
      const image = product.image_url
        ? `<img class="managed-product-thumb" src="${this.escape(product.image_url)}" alt="">`
        : '<span class="managed-product-thumb managed-product-thumb-empty" aria-hidden="true">—</span>';
      return `<tr>
        <td>${image}<strong>${this.escape(product.name)}</strong><div class="subtle-text">${this.escape(product.generic_name || product.barcode || '')}</div></td>
        <td>${this.escape(product.category_name)}</td>
        <td>${this.escape(product.unit_price)} / ${this.escape(product.unit_of_measure)}</td>
        <td>${product.available_stock_quantity} eligible · ${product.stock_quantity} on hand</td>
        <td>${batches}</td>
        <td>${locations}</td>
        <td><span class="badge-status ${product.active ? 'badge-status-in-stock' : 'badge-status-expiring'}">${product.active ? 'Active' : 'Inactive'}</span>${product.requires_prescription ? '<div class="subtle-text">Prescription</div>' : ''}</td>
        <td class="product-row-actions">
          <button class="btn btn-secondary btn-sm" type="button" data-edit-product="${product.id}">Edit</button>
          <button class="btn btn-secondary btn-sm" type="button" data-toggle-product="${product.id}" data-active="${product.active}">${product.active ? 'Deactivate' : 'Activate'}</button>
        </td>
      </tr>`;
    }).join('');
  }

  renderCategories() {
    const body = document.getElementById('managedCategoriesTableBody');
    if (!this.categories.length) {
      body.innerHTML = '<tr><td colspan="6" class="empty-state">No categories are configured.</td></tr>';
      return;
    }
    body.innerHTML = this.categories.map(category => `<tr data-category-row="${category.id}">
      <td>${category.image_url ? `<img class="managed-category-thumb" src="${this.escape(category.image_url)}" alt="">` : '—'}</td>
      <td><input data-category-name maxlength="80" value="${this.escape(category.name)}" aria-label="Category name"></td>
      <td><input data-category-description maxlength="1000" value="${this.escape(category.description || '')}" aria-label="Category description"></td>
      <td><input data-category-image maxlength="500" value="${this.escape(category.image_url || '')}" aria-label="Category image path"></td>
      <td><span class="badge-status ${category.active ? 'badge-status-in-stock' : 'badge-status-expiring'}">${category.active ? 'Active' : 'Inactive'}</span></td>
      <td class="product-row-actions">
        <button class="btn btn-secondary btn-sm" type="button" data-save-category="${category.id}">Save</button>
        <button class="btn btn-secondary btn-sm" type="button" data-toggle-category="${category.id}" data-active="${category.active}">${category.active ? 'Deactivate' : 'Activate'}</button>
      </td>
    </tr>`).join('');
  }

  async saveProduct() {
    const formData = new FormData(this.form);
    const productId = formData.get('product_id');
    const payload = {
      name: formData.get('name').trim(),
      generic_name: this.nullIfBlank(formData.get('generic_name')),
      barcode: this.nullIfBlank(formData.get('barcode')),
      category_id: Number(formData.get('category_id')),
      manufacturer: this.nullIfBlank(formData.get('manufacturer')),
      unit_of_measure: formData.get('unit_of_measure').trim(),
      unit_price: formData.get('unit_price'),
      min_threshold: Number(formData.get('min_threshold')),
      description: this.nullIfBlank(formData.get('description')),
      ingredients_strengths: this.nullIfBlank(formData.get('ingredients_strengths')),
      common_uses: this.nullIfBlank(formData.get('common_uses')),
      directions: this.nullIfBlank(formData.get('directions')),
      warnings: this.nullIfBlank(formData.get('warnings')),
      requires_prescription: formData.has('requires_prescription'),
      product_information_verified: formData.has('product_information_verified'),
      active: formData.has('active')
    };
    if (productId && Number(formData.get('category_id')) === this.editingOriginalCategoryId) {
      delete payload.category_id;
    }

    if (!productId && this.stockToggle.checked) {
      const quantity = formData.get('quantity');
      payload.initial_stock = {
        batch_number: formData.get('batch_number').trim(),
        manufacturing_date: this.nullIfBlank(formData.get('manufacturing_date')),
        expiry_date: formData.get('expiry_date'),
        purchase_date: formData.get('purchase_date'),
        quantity: Number(quantity),
        location_code: formData.get('location_code'),
        supplier_id: formData.get('supplier_id') ? Number(formData.get('supplier_id')) : null,
        purchase_price: this.nullIfBlank(formData.get('purchase_price')),
        unit_cost: this.nullIfBlank(formData.get('unit_cost'))
      };
    }

    const savedProduct = productId
      ? await PromedApi.patch(`/management/products/${productId}`, payload)
      : await PromedApi.post('/management/products', payload);
    const image = this.imageInput.files[0];
    if (image) {
      if (!productId) {
        this.form.elements.product_id.value = savedProduct.id;
        this.editingProductId = savedProduct.id;
        this.editingOriginalCategoryId = savedProduct.category_id;
        document.getElementById('productEditorHeading').textContent = `Edit ${savedProduct.name}`;
        document.getElementById('managedProductSubmit').textContent = 'Save changes';
        document.getElementById('cancelManagedProductEditBtn').hidden = false;
        this.stockToggle.closest('label').hidden = true;
        this.stockToggle.checked = false;
        this.stockFields.hidden = true;
      }
      try {
        await PromedApi.upload(`/management/products/${savedProduct.id}/image`, image);
      } catch (error) {
        await this.refresh();
        this.setStatus(
          `Product details were saved, but the image upload failed: ${error.message}`,
          true
        );
        return;
      }
    }
    this.setStatus(productId ? 'Product details saved.' : 'Product saved. Initial stock, if provided, was recorded through inventory receipts.', false);
    this.resetForm();
    await this.refresh();
  }

  async startEditing(productId) {
    const product = this.products.find(item => item.id === productId);
    if (!product) return;
    this.editingProductId = product.id;
    this.editingOriginalCategoryId = product.category_id;
    const form = this.form;
    form.elements.product_id.value = product.id;
    form.elements.name.value = product.name;
    form.elements.generic_name.value = product.generic_name || '';
    form.elements.barcode.value = product.barcode || '';
    form.elements.category_id.value = String(product.category_id);
    form.elements.manufacturer.value = product.manufacturer || '';
    form.elements.unit_of_measure.value = product.unit_of_measure;
    form.elements.unit_price.value = product.unit_price;
    form.elements.min_threshold.value = product.min_threshold;
    form.elements.description.value = product.description || '';
    form.elements.ingredients_strengths.value = product.ingredients_strengths || '';
    form.elements.common_uses.value = product.common_uses || '';
    form.elements.directions.value = product.directions || '';
    form.elements.warnings.value = product.warnings || '';
    form.elements.requires_prescription.checked = product.requires_prescription;
    form.elements.product_information_verified.checked = product.product_information_verified;
    form.elements.active.checked = product.active;
    form.elements.active.disabled = false;
    document.getElementById('productEditorHeading').textContent = `Edit ${product.name}`;
    document.getElementById('managedProductSubmit').textContent = 'Save changes';
    document.getElementById('cancelManagedProductEditBtn').hidden = false;
    this.stockToggle.closest('label').hidden = true;
    this.stockToggle.checked = false;
    this.stockFields.hidden = true;
    this.showImage(product.image_url);
    document.getElementById('removeManagedProductImageBtn').hidden = !product.image_url;
    document.getElementById('view-products').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async toggleProduct(productId, active) {
    await PromedApi.patch(`/management/products/${productId}`, { active: !active });
    this.setStatus(`Product ${active ? 'deactivated' : 'activated'}.`, false);
    await this.loadProducts();
  }

  async saveCategory(categoryId) {
    const row = document.querySelector(`[data-category-row="${categoryId}"]`);
    const payload = {
      name: row.querySelector('[data-category-name]').value.trim(),
      description: this.nullIfBlank(row.querySelector('[data-category-description]').value),
      image_url: this.nullIfBlank(row.querySelector('[data-category-image]').value)
    };
    await PromedApi.patch(`/categories/${categoryId}`, payload);
    this.setStatus('Category saved.', false);
    await this.loadCategories();
  }

  async toggleCategory(categoryId, active) {
    await PromedApi.patch(`/categories/${categoryId}`, { active: !active });
    this.setStatus(`Category ${active ? 'deactivated' : 'activated'}.`, false);
    await this.loadCategories();
    await this.loadProducts();
  }

  async createCategory(form) {
    const data = new FormData(form);
    await PromedApi.post('/categories', {
      name: data.get('name').trim(),
      description: this.nullIfBlank(data.get('description'))
    });
    form.reset();
    this.setStatus('Category created.', false);
    await this.loadCategories();
  }

  async removeImage() {
    const productId = this.form.elements.product_id.value;
    if (this.imageInput.files.length) this.imageInput.value = '';
    if (!productId) {
      this.showImage(null);
      return;
    }
    await PromedApi.delete(`/management/products/${productId}/image`);
    this.showImage(null);
    document.getElementById('removeManagedProductImageBtn').hidden = true;
    const product = this.products.find(item => item.id === Number(productId));
    if (product) product.image_url = null;
    this.setStatus('Product image removed.', false);
    await this.loadProducts();
  }

  previewSelectedImage() {
    const image = this.imageInput.files[0];
    if (!image) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(image.type) || image.size > 5 * 1024 * 1024) {
      this.imageInput.value = '';
      this.setStatus('Choose a JPG, PNG, or WebP image no larger than 5 MB.', true);
      return;
    }
    this.showImage(URL.createObjectURL(image), true);
  }

  showImage(imageUrl, temporary = false) {
    if (this.previewUrl) URL.revokeObjectURL(this.previewUrl);
    this.previewUrl = temporary ? imageUrl : null;
    this.imagePreview.hidden = !imageUrl;
    this.imagePreview.innerHTML = imageUrl
      ? `<img src="${this.escape(imageUrl)}" alt="Product image preview"><span>${temporary ? 'Preview before saving' : 'Current product image'}</span>`
      : '';
    document.getElementById('removeManagedProductImageBtn').hidden = !imageUrl || temporary;
  }

  updateStockFields() {
    const shown = this.stockToggle.checked && !this.editingProductId;
    this.stockFields.hidden = !shown;
    this.stockFields.querySelectorAll('[data-stock-required]').forEach(input => {
      input.required = shown;
    });
    ['batch_number', 'expiry_date', 'purchase_date', 'quantity', 'location_code'].forEach(name => {
      const input = this.form.elements[name];
      input.required = shown;
    });
  }

  resetForm() {
    this.form.reset();
    this.form.elements.product_id.value = '';
    this.editingProductId = null;
    this.editingOriginalCategoryId = null;
    this.form.elements.unit_of_measure.value = 'unit';
    this.form.elements.unit_price.value = '0.00';
    this.form.elements.min_threshold.value = '0';
    this.form.elements.active.checked = true;
    this.form.elements.active.disabled = false;
    this.stockToggle.closest('label').hidden = false;
    this.stockToggle.checked = false;
    this.updateStockFields();
    this.imageInput.value = '';
    this.showImage(null);
    document.getElementById('productEditorHeading').textContent = 'Add a product';
    document.getElementById('managedProductSubmit').textContent = 'Save product';
    document.getElementById('cancelManagedProductEditBtn').hidden = true;
  }

  setStatus(message, isError) {
    const status = document.getElementById('productManagementStatus');
    status.textContent = message;
    status.classList.toggle('is-error', isError);
  }

  nullIfBlank(value) {
    const normalized = String(value || '').trim();
    return normalized || null;
  }

  escape(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[character]);
  }
}
