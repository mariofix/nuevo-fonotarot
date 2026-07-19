const Cart = (() => {
  const KEY = 'cart';

  const LABEL = {
    minute_pack: 'Planes de Minutos',
    giftcard:    'Tarjetas de Regalo',
    product:     'Productos',
  };

  // ── storage ──────────────────────────────────────────────

  const load = () =>
    JSON.parse(localStorage.getItem(KEY) || '[]');

  const save = (items) =>
    localStorage.setItem(KEY, JSON.stringify(items));

  const csrf = () =>
    document.querySelector('meta[name="csrf-token"]')?.content ?? '';

  // ── events ───────────────────────────────────────────────

  const emit = (items) =>
    document.dispatchEvent(new CustomEvent('cart:updated', {
      detail: { items, count: count(items), total: total(items) }
    }));

  // ── public api ───────────────────────────────────────────

  // CartItem: { type, slug, qty, name?, price? }
  // type: 'minute_pack' | 'giftcard' | 'product'

  const add = (type, slug, qty = 1, name = null, price = null) => {
    const items = load();
    const found = items.find(i => i.type === type && i.slug === slug);
    if (found) {
      found.qty += qty;
    } else {
      items.push({
        type, slug, qty,
        ...(name  !== null && { name }),
        ...(price !== null && { price }),
      });
    }
    save(items);
    emit(items);
  };

  const remove = (type, slug) => {
    const items = load().filter(i => !(i.type === type && i.slug === slug));
    save(items);
    emit(items);
  };

  const update = (type, slug, qty) => {
    if (qty <= 0) return remove(type, slug);
    const items = load();
    const found = items.find(i => i.type === type && i.slug === slug);
    if (found) { found.qty = qty; save(items); emit(items); }
  };

  const clear = () => {
    localStorage.removeItem(KEY);
    emit([]);
  };

  const get  = () => load();

  const count = (items = load()) =>
    items.reduce((sum, i) => sum + i.qty, 0);

  const total = (items = load()) =>
    items.reduce((sum, i) => sum + (i.price ?? 0) * i.qty, 0);

  const checkout = async (meta = {}) => {
    const items = load();
    if (!items.length) return { ok: false, error: 'No tienes productos en tu carro.' };

    let res;
    try {
      const url = (typeof _CART_CHECKOUT_URL !== 'undefined' && _CART_CHECKOUT_URL)
        ? _CART_CHECKOUT_URL
        : '/cart/checkout';
      res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken':  csrf(),
        },
        body: JSON.stringify({ items, ...meta }),
      });
    } catch {
      return { ok: false, error: 'Error de conexión. Intenta nuevamente.' };
    }

    const data = await res.json().catch(() => ({}));
    if (res.ok && data.ok) {
      clear();
      return { ok: true, order: data.order };
    }
    return { ok: false, error: data.error || `Error del servidor (${res.status})` };
  };

  // ── UI renderer ──────────────────────────────────────────
  // Cart.UI.render(mountEl) — called automatically on show.bs.offcanvas

  const UI = (() => {
    // CLP: integer, thousands separator, no decimals
    const fmt = (n) => '$' + Math.round(Number(n)).toLocaleString('es-CL');

    const css = `
      .cart-item{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--tblr-border-color);}
      .cart-item:last-child{border-bottom:none;}
      .cart-item-name{font-size:.875rem;font-weight:500;margin:0 0 2px;}
      .cart-item-meta{font-size:.8rem;color:var(--tblr-secondary);margin:0;}
      .cart-qty{display:flex;align-items:center;gap:6px;margin-left:auto;flex-shrink:0;}
      .cart-qty-btn{width:26px;height:26px;border:1px solid var(--tblr-border-color);border-radius:4px;background:var(--tblr-bg-surface);color:var(--tblr-body-color);cursor:pointer;font-size:15px;display:flex;align-items:center;justify-content:center;line-height:1;padding:0;}
      .cart-qty-btn:hover{background:var(--tblr-bg-surface-secondary);}
      .cart-qty-num{font-size:.875rem;font-weight:500;min-width:18px;text-align:center;}
      .cart-remove{border:none;background:none;cursor:pointer;color:var(--tblr-secondary);display:flex;align-items:center;padding:4px;border-radius:4px;}
      .cart-remove:hover{color:var(--tblr-danger);background:rgba(var(--tblr-danger-rgb),.08);}
      .cart-empty{text-align:center;padding:3rem 1rem;color:var(--tblr-secondary);}
      .cart-footer{border-top:1px solid var(--tblr-border-color);padding-top:12px;margin-top:8px;}
      .cart-summary-row{display:flex;justify-content:space-between;font-size:.875rem;color:var(--tblr-secondary);padding:3px 0;}
      .cart-summary-total{font-size:1rem;font-weight:600;color:var(--tblr-body-color);}
      .cart-alert{font-size:.8125rem;border-radius:4px;padding:8px 12px;margin-bottom:10px;}
    `;

    let styleInjected = false;
    const injectStyle = () => {
      if (styleInjected) return;
      const s = document.createElement('style');
      s.textContent = css;
      document.head.appendChild(s);
      styleInjected = true;
    };

    // mount is stored so handleClick can re-render without DOM traversal
    let _mount = null;

    const render = (mount) => {
      injectStyle();
      if (!mount) return;
      _mount = mount;

      // remove stale listener before re-render
      mount.removeEventListener('click', handleClick);

      const items = load();

      if (!items.length) {
        mount.innerHTML = `
          <div class="cart-empty">
            <i class="ti ti-shopping-cart" style="font-size:2.5rem;display:block;margin-bottom:.5rem;"></i>
            No tienes productos en tu carro.
          </div>`;
        return;
      }

      const rows = items.map(i => `
        <div class="cart-item">
          <div style="flex:1;min-width:0;">
            <p class="cart-item-name">${i.name ?? i.slug}</p>
            <p class="cart-item-meta">
              ${i.price != null ? fmt(i.price) + ' &nbsp;' : ''}
              <span class="badge bg-secondary-lt">${LABEL[i.type] ?? i.type}</span>
            </p>
          </div>
          <div class="cart-qty">
            <button class="cart-qty-btn" data-action="dec" data-type="${i.type}" data-slug="${i.slug}" aria-label="Quitar uno">−</button>
            <span class="cart-qty-num">${i.qty}</span>
            <button class="cart-qty-btn" data-action="inc" data-type="${i.type}" data-slug="${i.slug}" aria-label="Agregar uno">+</button>
          </div>
          <button class="cart-remove" data-action="remove" data-type="${i.type}" data-slug="${i.slug}" aria-label="Eliminar ${i.name ?? i.slug}">
            <i class="ti ti-trash" style="font-size:16px;"></i>
          </button>
        </div>`).join('');

      mount.innerHTML = `
        <div id="cart-alert-msg" class="cart-alert" style="display:none;"></div>
        <div class="cart-items">${rows}</div>
        <div class="cart-footer">
          <div class="cart-summary-row">
            <span>Productos</span><span>${count(items)}</span>
          </div>
          <div class="cart-summary-row" style="padding-bottom:12px;border-bottom:1px solid var(--tblr-border-color);margin-bottom:12px;">
            <span>Total</span>
            <span class="cart-summary-total">${fmt(total(items))} CLP</span>
          </div>
          <button id="cart-checkout-btn" class="btn btn-primary w-100">
            <i class="ti ti-lock me-1"></i>Pagar
          </button>
        </div>`;

      mount.addEventListener('click', handleClick);
    };

    const handleClick = (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const { action, type, slug } = btn.dataset;
      if (action === 'inc')    update(type, slug, (load().find(i => i.type === type && i.slug === slug)?.qty ?? 0) + 1);
      if (action === 'dec')    update(type, slug, (load().find(i => i.type === type && i.slug === slug)?.qty ?? 1) - 1);
      if (action === 'remove') remove(type, slug);
      if (action === 'checkout') handleCheckout(_mount);
      render(_mount);
    };

    const showAlert = (mount, msg, variant) => {
      const el = mount?.querySelector('#cart-alert-msg');
      if (!el) return;
      el.className = `cart-alert alert alert-${variant}`;
      el.textContent = msg;
      el.style.display = 'block';
      setTimeout(() => { el.style.display = 'none'; }, 4000);
    };

    const handleCheckout = async (mount) => {
      const btn = document.getElementById('cart-checkout-btn');
      if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Procesando...'; }

      const result = await checkout();

      if (result.ok) {
        render(mount);
        showAlert(mount, '¡Gracias! Tu pedido fue recibido.', 'success');
      } else {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ti ti-lock me-1"></i>Pagar'; }
        showAlert(mount, result.error, 'danger');
      }
    };

    return { render };
  })();

  // ── offcanvas + badge wiring ─────────────────────────────

  document.addEventListener('DOMContentLoaded', () => {
    // restore trigger visibility on page load if cart has items
    const initCount = count();
    if (initCount > 0) {
      const trigger = document.getElementById('cart-trigger');
      const badge   = document.getElementById('cart-badge');
      if (trigger) { trigger.style.display = 'inline-flex'; trigger.style.opacity = '1'; }
      if (badge)   badge.textContent = initCount;
    }

    // re-render cart on offcanvas open
    const offcanvas = document.getElementById('cart-offcanvas');
    if (offcanvas) {
      offcanvas.addEventListener('show.bs.offcanvas', () => {
        UI.render(document.getElementById('cart-root'));
      });
    }

    // keep trigger + badge in sync
    document.addEventListener('cart:updated', ({ detail }) => {
      const badge   = document.getElementById('cart-badge');
      const trigger = document.getElementById('cart-trigger');

      if (badge) badge.textContent = detail.count;

      if (trigger) {
        if (detail.count > 0) {
          trigger.style.display = 'inline-flex';
          requestAnimationFrame(() => { trigger.style.opacity = '1'; });
        } else {
          trigger.style.opacity = '0';
          trigger.addEventListener('transitionend', () => {
            trigger.style.display = 'none';
          }, { once: true });
        }
      }
    });
  });

  return { add, remove, update, clear, get, count, total, checkout, UI };
})();
