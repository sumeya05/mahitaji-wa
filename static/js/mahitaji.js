/* ==========================================================================
   Mahitaji storefront JavaScript (vanilla, no dependencies)
   Modules: utils, toasts, header/nav, search suggestions, cart, wishlist,
   catalog filters, forms, product page, chat assistant, misc UI.
   ========================================================================== */
(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const CONFIG = window.MAHITAJI || {};
  const URLS = CONFIG.urls || {};

  /* ---------------------------------------------------------------------
     Utils
     --------------------------------------------------------------------- */
  function getCookie(name) {
    const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : null;
  }
  const csrfToken = () => CONFIG.csrf || getCookie('csrftoken');

  async function request(url, { method = 'GET', data = null, form = null } = {}) {
    const headers = { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' };
    const options = { method, headers, credentials: 'same-origin' };
    if (method !== 'GET') headers['X-CSRFToken'] = csrfToken();
    if (form) {
      options.body = form;
    } else if (data) {
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(data);
    }
    const response = await fetch(url, options);
    let payload = {};
    try { payload = await response.json(); } catch (e) { payload = { ok: response.ok }; }
    if (payload.ok === undefined) payload.ok = response.ok;
    payload._status = response.status;
    return payload;
  }

  const money = (n) => 'KSh ' + Number(n).toLocaleString('en-KE', { maximumFractionDigits: 2 });
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* ---------------------------------------------------------------------
     Toasts
     --------------------------------------------------------------------- */
  const Toast = {
    box() {
      let el = $('.toasts');
      if (!el) { el = document.createElement('div'); el.className = 'toasts'; document.body.appendChild(el); }
      return el;
    },
    show(message, type = 'success', { html = false, timeout = 3800 } = {}) {
      const icons = { success: 'fa-circle-check', danger: 'fa-circle-exclamation', info: 'fa-circle-info', warning: 'fa-triangle-exclamation' };
      const el = document.createElement('div');
      el.className = `toast toast-${type}`;
      el.setAttribute('role', 'status');
      el.innerHTML = `<i class="fa-solid ${icons[type] || icons.info}"></i><div>${html ? message : escapeHtml(message)}</div><button class="toast-close" aria-label="Dismiss">&times;</button>`;
      this.box().appendChild(el);
      const remove = () => { el.classList.add('is-leaving'); setTimeout(() => el.remove(), 250); };
      el.querySelector('.toast-close').addEventListener('click', remove);
      if (timeout) setTimeout(remove, timeout);
      return el;
    },
  };
  window.MahitajiToast = Toast;

  /* ---------------------------------------------------------------------
     Header, drawers, mega menu
     --------------------------------------------------------------------- */
  const overlay = $('#overlay');
  let openDrawer = null;

  function openPanel(id) {
    const panel = $(id);
    if (!panel) return;
    closePanel();
    panel.classList.add('is-open');
    overlay && overlay.classList.add('is-open');
    document.body.classList.add('no-scroll');
    openDrawer = panel;
    const focusable = panel.querySelector('input, button, a');
    focusable && focusable.focus({ preventScroll: true });
  }
  function closePanel() {
    if (openDrawer) openDrawer.classList.remove('is-open');
    openDrawer = null;
    overlay && overlay.classList.remove('is-open');
    document.body.classList.remove('no-scroll');
  }
  window.MahitajiPanels = { open: openPanel, close: closePanel };
  // QA hook: /?_open=cartDrawer opens a panel on load.
  const openParam = new URLSearchParams(location.search).get('_open');
  if (openParam) setTimeout(() => openPanel('#' + openParam), 50);

  document.addEventListener('click', (e) => {
    const opener = e.target.closest('[data-open]');
    if (opener) { e.preventDefault(); openPanel(opener.getAttribute('data-open')); return; }
    if (e.target.closest('[data-close]') || e.target === overlay) { closePanel(); }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closePanel(); closeMega(); closeSuggest(); $$('.modal.is-open').forEach((m) => m.classList.remove('is-open')); }
  });

  // Mega menu
  const megaBtn = $('#megaBtn');
  const mega = $('#mega');
  function closeMega() { mega && mega.classList.remove('is-open'); megaBtn && megaBtn.setAttribute('aria-expanded', 'false'); }
  if (megaBtn && mega) {
    megaBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = mega.classList.toggle('is-open');
      megaBtn.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', (e) => { if (!mega.contains(e.target)) closeMega(); });
  }

  // Mobile search toggle
  const searchToggle = $('#searchToggle');
  const searchBox = $('#headerSearch');
  if (searchToggle && searchBox) {
    searchToggle.addEventListener('click', () => {
      const open = searchBox.classList.toggle('is-open');
      if (open) searchBox.querySelector('input[name="q"]').focus();
    });
  }

  // Sticky shadow + back-to-top
  const header = $('.header');
  const backTop = $('#backTop');
  const onScroll = () => {
    if (header) header.classList.toggle('is-stuck', window.scrollY > 8);
    if (backTop) backTop.classList.toggle('is-visible', window.scrollY > 600);
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
  backTop && backTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));

  /* ---------------------------------------------------------------------
     Search suggestions
     --------------------------------------------------------------------- */
  const suggest = $('#searchSuggest');
  const searchInput = $('#searchInput');
  let activeIndex = -1;
  function closeSuggest() { if (suggest) { suggest.classList.remove('is-open'); activeIndex = -1; } }
  function renderSuggest(data, q) {
    if (!suggest) return;
    const items = [];
    if (data.products.length) {
      items.push('<div class="sg-title">Products</div>');
      data.products.forEach((p) => {
        const thumb = p.has_image ? `<img src="${p.image}" alt="">` : `<span style="color:var(--brand-700)">${escapeHtml(p.initials)}</span>`;
        items.push(`<a class="sg-item" href="${p.url}"><span class="sg-thumb">${thumb}</span><span><span class="sg-name">${escapeHtml(p.name)}</span><br><span class="sg-meta">${escapeHtml(p.brand)}</span></span><span class="sg-price">${money(p.price)}</span></a>`);
      });
    }
    if (data.categories.length) {
      items.push('<div class="sg-title">Categories</div>');
      data.categories.forEach((c) => items.push(`<a class="sg-item" href="${c.url}"><span class="sg-thumb"><i class="fa-solid fa-tags"></i></span><span class="sg-name">${escapeHtml(c.name)}</span></a>`));
    }
    if (data.brands.length) {
      items.push('<div class="sg-title">Brands</div>');
      data.brands.forEach((b) => items.push(`<a class="sg-item" href="${b.url}"><span class="sg-thumb"><i class="fa-solid fa-industry"></i></span><span class="sg-name">${escapeHtml(b.name)}</span></a>`));
    }
    if (!items.length) items.push(`<div class="sg-empty">No matches for “${escapeHtml(q)}”. Press Enter to search anyway.</div>`);
    items.push(`<a class="sg-item" href="${URLS.search}?q=${encodeURIComponent(q)}"><span class="sg-thumb"><i class="fa-solid fa-magnifying-glass"></i></span><span class="sg-name">See all results for “${escapeHtml(q)}”</span></a>`);
    suggest.innerHTML = items.join('');
    suggest.classList.add('is-open');
    activeIndex = -1;
  }
  if (searchInput && suggest && URLS.suggest) {
    const fetchSuggest = debounce(async (q) => {
      if (q.length < 2) return closeSuggest();
      try {
        const data = await request(`${URLS.suggest}?q=${encodeURIComponent(q)}`);
        if (searchInput.value.trim() === q) renderSuggest(data, q);
      } catch (e) { closeSuggest(); }
    }, 220);
    searchInput.addEventListener('input', () => fetchSuggest(searchInput.value.trim()));
    searchInput.addEventListener('focus', () => { if (searchInput.value.trim().length >= 2 && suggest.innerHTML) suggest.classList.add('is-open'); });
    searchInput.addEventListener('keydown', (e) => {
      const links = $$('.sg-item', suggest);
      if (!suggest.classList.contains('is-open') || !links.length) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        activeIndex = (activeIndex + (e.key === 'ArrowDown' ? 1 : -1) + links.length) % links.length;
        links.forEach((l, i) => l.classList.toggle('is-active', i === activeIndex));
        links[activeIndex].scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter' && activeIndex >= 0) {
        e.preventDefault();
        window.location.href = links[activeIndex].href;
      }
    });
    document.addEventListener('click', (e) => { if (!e.target.closest('.search')) closeSuggest(); });
  }

  /* ---------------------------------------------------------------------
     Cart
     --------------------------------------------------------------------- */
  const Cart = {
    apply(summary) {
      if (!summary) return;
      $$('[data-cart-count]').forEach((el) => { el.textContent = summary.qty; el.classList.toggle('is-zero', !summary.qty); });
      $$('[data-cart-total]').forEach((el) => { el.textContent = money(summary.total); });
      $$('[data-cart-lines]').forEach((el) => { el.textContent = summary.lines; });
      document.body.classList.toggle('cart-empty', !summary.qty);
    },
    drawer(html) {
      const body = $('#cartDrawerBody');
      if (body && html !== undefined) body.innerHTML = html;
    },
    markCards(productId, qty) {
      $$(`.pc[data-product-id="${productId}"]`).forEach((card) => {
        card.classList.toggle('in-cart', qty > 0);
        const input = card.querySelector('.qty input');
        if (input) input.value = qty;
      });
    },
    // The drawer is only opened when the customer asks for it (header button / "View cart"),
    // never automatically after an add.
    async add(productId, qty = 1, { openDrawer = false, silent = false } = {}) {
      const res = await request(URLS.cartAdd, { method: 'POST', data: { product_id: productId, product_qty: qty } });
      if (!res.ok) { Toast.show(res.error || 'Could not add to cart.', 'danger'); return res; }
      this.apply(res.cart); this.drawer(res.drawer_html);
      if (res.product) this.markCards(res.product.id, res.product.qty);
      if (!silent) Toast.show(`${res.message} <a href="${URLS.cart}">View cart</a>`, 'success', { html: true });
      if (openDrawer && window.innerWidth >= 992) openPanel('#cartDrawer');
      return res;
    },
    async update(productId, qty) {
      const res = await request(URLS.cartUpdate, { method: 'POST', data: { product_id: productId, product_qty: qty } });
      if (!res.ok) { Toast.show(res.error || 'Could not update cart.', 'danger'); return res; }
      this.apply(res.cart); this.drawer(res.drawer_html);
      this.markCards(productId, qty);
      const row = $(`[data-cart-row="${productId}"]`);
      if (row) {
        const lineEl = row.querySelector('[data-line-total]');
        if (qty <= 0) row.remove(); else if (lineEl) lineEl.textContent = money(res.line_total);
      }
      checkEmptyCartPage(res.cart);
      return res;
    },
    async remove(productId) {
      const res = await request(URLS.cartDelete, { method: 'POST', data: { product_id: productId } });
      if (!res.ok) { Toast.show(res.error || 'Could not remove item.', 'danger'); return res; }
      this.apply(res.cart); this.drawer(res.drawer_html); this.markCards(productId, 0);
      const row = $(`[data-cart-row="${productId}"]`);
      row && row.remove();
      checkEmptyCartPage(res.cart);
      Toast.show(res.message || 'Item removed.', 'info');
      return res;
    },
  };
  window.MahitajiCart = Cart;

  function checkEmptyCartPage(summary) {
    const page = $('#cartPage');
    if (page && summary && !summary.qty) window.location.reload();
  }

  function setBusy(btn, busy, label) {
    if (!btn) return;
    if (busy) {
      btn.dataset.label = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner"></span>${label ? ' ' + label : ''}`;
    } else {
      btn.disabled = false;
      if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
    }
  }

  document.addEventListener('click', async (e) => {
    const add = e.target.closest('[data-add-to-cart]');
    if (add) {
      e.preventDefault();
      const id = add.getAttribute('data-add-to-cart');
      const qtyInput = add.closest('[data-buy-box]') ? add.closest('[data-buy-box]').querySelector('input[name="qty"]') : null;
      const qty = qtyInput ? parseInt(qtyInput.value, 10) || 1 : 1;
      setBusy(add, true);
      try { await Cart.add(id, qty); } finally { setBusy(add, false); }
      return;
    }
    const remove = e.target.closest('[data-cart-remove]');
    if (remove) {
      e.preventDefault();
      await Cart.remove(remove.getAttribute('data-cart-remove'));
      return;
    }
    const step = e.target.closest('.qty button');
    if (step) {
      e.preventDefault();
      const wrap = step.closest('.qty');
      const input = wrap.querySelector('input');
      const min = parseInt(input.min || '0', 10);
      let value = parseInt(input.value, 10) || 0;
      value += step.classList.contains('qty-plus') ? 1 : -1;
      if (value < min) value = min;
      input.value = value;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }
  });

  document.addEventListener('change', async (e) => {
    const input = e.target.closest('.qty input[data-cart-qty]');
    if (!input) return;
    let qty = parseInt(input.value, 10);
    if (isNaN(qty) || qty < 0) qty = 0;
    await Cart.update(input.getAttribute('data-cart-qty'), qty);
  });

  /* ---------------------------------------------------------------------
     Wishlist
     --------------------------------------------------------------------- */
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-wishlist]');
    if (!btn) return;
    e.preventDefault();
    const id = btn.getAttribute('data-wishlist');
    const res = await request(URLS.wishlistToggle, { method: 'POST', data: { product_id: id } });
    if (res._status === 401) {
      Toast.show(`Sign in to save products. <a href="${URLS.login}?next=${encodeURIComponent(location.pathname)}">Sign in</a>`, 'info', { html: true });
      return;
    }
    if (!res.ok) { Toast.show(res.error || 'Could not update wishlist.', 'danger'); return; }
    $$(`[data-wishlist="${id}"]`).forEach((b) => {
      b.classList.toggle('is-active', res.added);
      b.setAttribute('aria-pressed', String(res.added));
      const icon = b.querySelector('i');
      if (icon) icon.className = res.added ? 'fa-solid fa-heart' : 'fa-regular fa-heart';
    });
    $$('[data-wishlist-count]').forEach((el) => { el.textContent = res.count; el.classList.toggle('is-zero', !res.count); });
    if (!res.added && btn.hasAttribute('data-wishlist-remove-row')) { const row = btn.closest('[data-wishlist-row]'); row && row.remove(); }
    Toast.show(res.message, res.added ? 'success' : 'info');
  });

  /* ---------------------------------------------------------------------
     Catalog: filters, sort, pagination via AJAX
     --------------------------------------------------------------------- */
  const catalogEl = $('#catalog');
  if (catalogEl) {
    const results = $('#catalogResults');
    const grid = () => $('#productGrid') || results;
    const baseUrl = catalogEl.getAttribute('data-url') || location.pathname;

    function collectParams() {
      const params = new URLSearchParams();
      const q = catalogEl.getAttribute('data-q');
      if (q) params.set('q', q);
      $$('input[data-filter="category"]:checked').forEach((cb) => params.append('category', cb.value));
      $$('input[data-filter="brand"]:checked').forEach((cb) => params.append('brand', cb.value));
      const sort = $('#sortSelect');
      if (sort && sort.value && sort.value !== 'featured') params.set('sort', sort.value);
      return params;
    }

    async function load(params, { push = true } = {}) {
      const url = baseUrl + (params.toString() ? '?' + params.toString() : '');
      grid().classList.add('is-loading');
      try {
        const res = await request(url);
        if (res.ok && res.html !== undefined) {
          results.innerHTML = res.html;
          $$('[data-result-count]').forEach((el) => { el.textContent = res.count; });
          if (push) history.pushState({ catalog: true }, '', url);
          syncChips(params);
          if (window.scrollY > results.getBoundingClientRect().top + window.scrollY - 140) {
            results.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        }
      } catch (err) { Toast.show('Could not load products. Please retry.', 'danger'); }
      finally { grid().classList.remove('is-loading'); }
    }

    function syncChips(params) {
      const box = $('#activeFilters');
      if (!box) return;
      const chips = [];
      ['category', 'brand'].forEach((key) => {
        params.getAll(key).forEach((slug) => {
          const cb = $(`input[data-filter="${key}"][value="${CSS.escape(slug)}"]`);
          const label = cb ? cb.getAttribute('data-label') : slug;
          chips.push(`<button class="chip is-active" data-chip="${key}" data-value="${escapeHtml(slug)}">${escapeHtml(label)} <i class="fa-solid fa-xmark chip-x"></i></button>`);
        });
      });
      if (chips.length) chips.push('<button class="chip" id="clearFilters"><i class="fa-solid fa-rotate-left"></i> Clear all</button>');
      box.innerHTML = chips.join('');
      box.classList.toggle('hidden', !chips.length);
    }

    document.addEventListener('change', (e) => {
      if (e.target.matches('input[data-filter]')) {
        // Keep the mobile drawer and desktop sidebar in sync.
        $$(`input[data-filter="${e.target.getAttribute('data-filter')}"][value="${CSS.escape(e.target.value)}"]`).forEach((cb) => { cb.checked = e.target.checked; });
        load(collectParams());
      }
      if (e.target.id === 'sortSelect') load(collectParams());
    });
    document.addEventListener('click', (e) => {
      const chip = e.target.closest('[data-chip]');
      if (chip) {
        $$(`input[data-filter="${chip.getAttribute('data-chip')}"][value="${CSS.escape(chip.getAttribute('data-value'))}"]`).forEach((cb) => { cb.checked = false; });
        load(collectParams());
        return;
      }
      if (e.target.closest('#clearFilters')) {
        $$('input[data-filter]').forEach((cb) => { cb.checked = false; });
        load(collectParams());
        return;
      }
      const pageLink = e.target.closest('#catalogResults .pagination a');
      if (pageLink) {
        e.preventDefault();
        const params = new URLSearchParams(pageLink.getAttribute('href').replace(/^\?/, ''));
        load(params);
      }
    });
    document.addEventListener('input', debounce((e) => {
      if (!e.target.matches('[data-filter-search]')) return;
      const term = e.target.value.toLowerCase();
      const list = e.target.closest('.card').querySelector('.filter-list');
      $$('label', list).forEach((label) => { label.classList.toggle('hidden', !label.textContent.toLowerCase().includes(term)); });
    }, 120));
    window.addEventListener('popstate', () => {
      const params = new URLSearchParams(location.search);
      $$('input[data-filter]').forEach((cb) => { cb.checked = params.getAll(cb.getAttribute('data-filter')).includes(cb.value); });
      const sort = $('#sortSelect'); if (sort) sort.value = params.get('sort') || 'featured';
      load(params, { push: false });
    });
    syncChips(new URLSearchParams(location.search));
  }

  /* ---------------------------------------------------------------------
     AJAX forms: <form data-ajax> with inline field errors
     --------------------------------------------------------------------- */
  function clearErrors(form) {
    $$('.field.has-error', form).forEach((f) => f.classList.remove('has-error'));
    $$('.field-error[data-generated]', form).forEach((f) => f.remove());
    const alert = form.querySelector('[data-form-alert]');
    if (alert) { alert.classList.remove('is-visible'); alert.textContent = ''; }
  }
  function showErrors(form, res) {
    const alert = form.querySelector('[data-form-alert]');
    const errors = res.errors || {};
    let first = null;
    Object.entries(errors).forEach(([name, msgs]) => {
      const input = form.querySelector(`[name="${name}"]`);
      const field = input ? input.closest('.field') : null;
      if (field) {
        field.classList.add('has-error');
        const span = document.createElement('span');
        span.className = 'field-error'; span.setAttribute('data-generated', '1');
        span.textContent = Array.isArray(msgs) ? msgs.join(' ') : String(msgs);
        field.appendChild(span);
        if (!first) first = input;
      }
    });
    const general = (errors.__all__ && errors.__all__.join(' ')) || res.error || 'Something went wrong. Please try again.';
    if (alert) { alert.textContent = general; alert.classList.add('is-visible'); }
    else Toast.show(general, 'danger');
    first && first.focus();
  }
  document.addEventListener('submit', async (e) => {
    const form = e.target.closest('form[data-ajax]');
    if (!form) return;
    e.preventDefault();
    const btn = form.querySelector('[type="submit"]');
    clearErrors(form);
    setBusy(btn, true, btn && btn.getAttribute('data-busy'));
    try {
      const res = await request(form.getAttribute('action') || location.href, { method: 'POST', form: new FormData(form) });
      if (res.ok) {
        if (res.redirect_url) { window.location.href = res.redirect_url; return; }
        if (res.message) Toast.show(res.message, 'success');
        if (form.hasAttribute('data-reset')) form.reset();
        form.dispatchEvent(new CustomEvent('ajax:success', { detail: res }));
      } else {
        showErrors(form, res);
      }
    } catch (err) {
      Toast.show('Connection problem. Please check your internet and try again.', 'danger');
    } finally { setBusy(btn, false); }
  });

  /* ---------------------------------------------------------------------
     Small UI helpers: tabs, password toggle, reveal, modal, pay options
     --------------------------------------------------------------------- */
  document.addEventListener('click', (e) => {
    const tab = e.target.closest('[data-tab]');
    if (tab) {
      e.preventDefault();
      const group = tab.closest('[data-tabs]') || document;
      $$('[data-tab]', group).forEach((t) => t.classList.toggle('is-active', t === tab));
      $$('.tab-panel', group).forEach((p) => p.classList.toggle('is-active', p.id === tab.getAttribute('data-tab')));
    }
    const toggle = e.target.closest('[data-toggle-password]');
    if (toggle) {
      e.preventDefault();
      const input = $('#' + toggle.getAttribute('data-toggle-password'));
      if (input) { const show = input.type === 'password'; input.type = show ? 'text' : 'password'; toggle.textContent = show ? 'Hide' : 'Show'; }
    }
    const modalOpen = e.target.closest('[data-modal]');
    if (modalOpen) { e.preventDefault(); const m = $(modalOpen.getAttribute('data-modal')); m && m.classList.add('is-open'); }
    if (e.target.closest('[data-modal-close]') || e.target.classList.contains('modal')) { $$('.modal.is-open').forEach((m) => m.classList.remove('is-open')); }
    const confirmEl = e.target.closest('[data-confirm]');
    if (confirmEl && !window.confirm(confirmEl.getAttribute('data-confirm'))) { e.preventDefault(); e.stopImmediatePropagation(); }
  });
  document.addEventListener('change', (e) => {
    if (e.target.matches('.pay-option input[type="radio"]')) {
      $$('.pay-option').forEach((o) => o.classList.toggle('is-selected', o.contains(e.target)));
    }
  });
  $$('.pay-option input[type="radio"]:checked').forEach((r) => r.closest('.pay-option').classList.add('is-selected'));

  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => { if (entry.isIntersecting) { entry.target.classList.add('is-in'); io.unobserve(entry.target); } });
    }, { threshold: 0.12 });
    $$('.reveal').forEach((el) => io.observe(el));
  } else { $$('.reveal').forEach((el) => el.classList.add('is-in')); }

  // Order details modal (account pages)
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-order-details]');
    if (!btn) return;
    e.preventDefault();
    const modal = $('#orderModal');
    if (!modal) return;
    const body = $('#orderModalBody');
    $('#orderModalTitle').textContent = btn.getAttribute('data-order-number') || 'Order';
    body.innerHTML = '<div class="text-center" style="padding:30px"><span class="spinner"></span></div>';
    modal.classList.add('is-open');
    try {
      const res = await fetch(btn.getAttribute('data-order-details'), { credentials: 'same-origin' });
      body.innerHTML = await res.text();
    } catch (err) { body.innerHTML = '<p class="muted">Could not load this order. Please try again.</p>'; }
  });

  /* ---------------------------------------------------------------------
     Newsletter (any form[data-newsletter])
     --------------------------------------------------------------------- */
  document.addEventListener('submit', async (e) => {
    const form = e.target.closest('form[data-newsletter]');
    if (!form) return;
    e.preventDefault();
    const btn = form.querySelector('button');
    setBusy(btn, true);
    try {
      const res = await request(form.action, { method: 'POST', form: new FormData(form) });
      Toast.show(res.ok ? res.message : (res.error || 'Please enter a valid email.'), res.ok ? 'success' : 'danger');
      if (res.ok) form.reset();
    } finally { setBusy(btn, false); }
  });

  /* ---------------------------------------------------------------------
     Chat assistant
     --------------------------------------------------------------------- */
  const chatFab = $('#chatFab');
  const chat = $('#chat');
  if (chatFab && chat) {
    const body = $('#chatBody');
    const input = $('#chatInput');
    const send = $('#chatSend');
    const KEY = 'mahitaji_chat_v2';
    let history = [];
    try { history = JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (e) { history = []; }

    function append(text, role, links) {
      const el = document.createElement('div');
      el.className = `msg ${role}`;
      el.textContent = text;
      if (links && links.length) {
        const wrap = document.createElement('div');
        wrap.className = 'msg-links';
        links.forEach((l) => { const a = document.createElement('a'); a.href = l.url; a.textContent = l.name; wrap.appendChild(a); });
        el.appendChild(wrap);
      }
      body.appendChild(el);
      body.scrollTop = body.scrollHeight;
      return el;
    }
    history.forEach((m) => append(m.text, m.role, m.links));
    if (!history.length) append("Hi! I'm the Mahitaji assistant. Ask me about products, prices, delivery or payments.", 'assistant');

    function toggleChat(open) {
      const isOpen = open === undefined ? !chat.classList.contains('is-open') : open;
      chat.classList.toggle('is-open', isOpen);
      chatFab.classList.toggle('is-open', isOpen);
      chatFab.innerHTML = isOpen ? '<i class="fa-solid fa-xmark"></i>' : '<i class="fa-solid fa-comment-dots"></i>';
      if (isOpen) input.focus();
    }
    chatFab.addEventListener('click', () => toggleChat());
    $('#chatClose') && $('#chatClose').addEventListener('click', () => toggleChat(false));

    async function ask(text) {
      const message = (text || input.value).trim();
      if (!message) return;
      input.value = '';
      append(message, 'user');
      history.push({ role: 'user', text: message });
      const typing = append('Thinking…', 'assistant typing');
      send.disabled = true;
      try {
        const res = await request(URLS.chat, { method: 'POST', data: { message } });
        typing.remove();
        const reply = res.reply || res.error || 'Sorry, something went wrong.';
        append(reply, 'assistant', res.products);
        history.push({ role: 'assistant', text: reply, links: res.products || [] });
        localStorage.setItem(KEY, JSON.stringify(history.slice(-30)));
      } catch (err) {
        typing.remove();
        append('Connection error. Please try again.', 'assistant');
      } finally { send.disabled = false; input.focus(); }
    }
    send.addEventListener('click', () => ask());
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); ask(); } });
    $$('[data-chat-quick]').forEach((b) => b.addEventListener('click', () => ask(b.getAttribute('data-chat-quick'))));
    $('#chatClear') && $('#chatClear').addEventListener('click', () => { history = []; localStorage.removeItem(KEY); body.innerHTML = ''; append("Chat cleared. How can I help?", 'assistant'); });
  }

  /* ---------------------------------------------------------------------
     Auto-dismiss Django messages
     --------------------------------------------------------------------- */
  $$('.messages .alert').forEach((el) => {
    const close = document.createElement('button');
    close.className = 'toast-close'; close.style.marginLeft = 'auto'; close.style.color = 'inherit'; close.innerHTML = '&times;'; close.setAttribute('aria-label', 'Dismiss');
    close.addEventListener('click', () => el.remove());
    el.appendChild(close);
  });

  window.MahitajiUtils = { request, money, Toast, setBusy, escapeHtml };
})();
