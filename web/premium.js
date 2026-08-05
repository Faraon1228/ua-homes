/**
 * UA-Dim Premium Tiers — Pricing modal + LiqPay payment flow
 * Автоматично підключається до backend /api/payment/liqpay/create
 */
(function () {
  'use strict';

  var API_BASE = (typeof UA_HOMES_API !== 'undefined' && UA_HOMES_API && UA_HOMES_API !== '__UA_HOMES_API__')
    ? UA_HOMES_API
    : 'https://backend-production-51964.up.railway.app';

  // ── Тарифи ────────────────────────────────────────────────────────────────
  var PLANS = [
    {
      id: 'free',
      name: 'Базовий',
      price: 0,
      period: 'безкоштовно',
      badge: null,
      color: '#64748b',
      bg: '#f8fafc',
      border: '#e2e8f0',
      features: [
        '1 оголошення',
        '30 днів активності',
        'Стандартна позиція',
        'Телефон прихований',
      ],
      limits: ['Без виділення', 'Без ТОП-позиції'],
      cta: 'Поточний план',
      disabled: true,
    },
    {
      id: 'standard',
      name: 'Стандарт',
      price: 299,
      period: 'міс',
      badge: null,
      color: '#2563eb',
      bg: '#eff6ff',
      border: '#bfdbfe',
      features: [
        '5 оголошень',
        '60 днів активності',
        'Виділення в пошуку',
        'Телефон відкритий',
        'Статистика переглядів',
      ],
      limits: ['Без ТОП-позиції'],
      cta: 'Підключити',
      disabled: false,
    },
    {
      id: 'premium',
      name: 'Преміум',
      price: 699,
      period: 'міс',
      badge: '🔥 Популярний',
      color: '#7c3aed',
      bg: '#f5f3ff',
      border: '#ddd6fe',
      features: [
        '15 оголошень',
        '90 днів активності',
        'ТОП-позиція в пошуку',
        'Бейдж «Перевірено»',
        'Телефон + WhatsApp',
        'Детальна аналітика',
        'Пріоритетна підтримка',
      ],
      limits: [],
      cta: 'Підключити',
      disabled: false,
    },
    {
      id: 'agent',
      name: 'Топ-агент',
      price: 1499,
      period: 'міс',
      badge: '⭐ Для агентів',
      color: '#b45309',
      bg: '#fffbeb',
      border: '#fde68a',
      features: [
        'Необмежено оголошень',
        '120 днів активності',
        'ТОП × 3 позиції',
        'Брендинг агентства',
        'CRM-інтеграція',
        'API доступ',
        'Особистий менеджер',
        'Верифікація агентства',
      ],
      limits: [],
      cta: 'Підключити',
      disabled: false,
    },
  ];

  // ── Стилі ─────────────────────────────────────────────────────────────────
  var STYLE = `
    #ua-premium-backdrop {
      position:fixed;inset:0;background:rgba(15,23,42,.7);backdrop-filter:blur(4px);
      z-index:9000;display:flex;align-items:center;justify-content:center;padding:16px;
      animation:ua-fade-in .2s ease;
    }
    #ua-premium-modal {
      background:#0f172a;border:1px solid #1e293b;border-radius:24px;
      width:100%;max-width:960px;max-height:90vh;overflow-y:auto;padding:36px 32px;
      position:relative;animation:ua-slide-up .25s ease;
    }
    .ua-pm-close {
      position:absolute;top:16px;right:20px;background:transparent;border:none;
      color:#94a3b8;font-size:22px;cursor:pointer;line-height:1;padding:4px;
    }
    .ua-pm-close:hover{color:#f1f5f9}
    .ua-pm-title {
      font-size:clamp(18px,3vw,26px);font-weight:800;color:#f1f5f9;
      text-align:center;margin:0 0 6px;
    }
    .ua-pm-sub {
      text-align:center;color:#94a3b8;font-size:14px;margin:0 0 32px;
    }
    .ua-pm-grid {
      display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;
    }
    .ua-pm-card {
      background:#1e293b;border-radius:16px;border:1.5px solid #334155;padding:24px 20px;
      display:flex;flex-direction:column;gap:0;transition:transform .2s,border-color .2s;
      position:relative;
    }
    .ua-pm-card:hover:not(.ua-pm-card--disabled){transform:translateY(-4px);border-color:var(--plan-color)}
    .ua-pm-card--popular{border-color:#7c3aed;box-shadow:0 0 0 1px #7c3aed30}
    .ua-pm-card--disabled{opacity:.7}
    .ua-pm-badge {
      position:absolute;top:-12px;left:50%;transform:translateX(-50%);
      background:var(--plan-color);color:#fff;font-size:11px;font-weight:700;
      padding:3px 12px;border-radius:999px;white-space:nowrap;
    }
    .ua-pm-name {font-size:13px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}
    .ua-pm-price {font-size:32px;font-weight:900;color:#f1f5f9;line-height:1}
    .ua-pm-price span {font-size:14px;font-weight:500;color:#64748b}
    .ua-pm-features {list-style:none;padding:0;margin:16px 0;display:flex;flex-direction:column;gap:8px;flex:1}
    .ua-pm-features li {font-size:13px;color:#cbd5e1;display:flex;gap:8px;align-items:flex-start}
    .ua-pm-features li::before {content:"✓";color:#22c55e;font-weight:700;flex-shrink:0}
    .ua-pm-limits li::before {content:"–";color:#ef4444}
    .ua-pm-limits li {color:#64748b}
    .ua-pm-btn {
      margin-top:auto;padding:12px;border-radius:12px;font-weight:700;font-size:14px;
      border:none;cursor:pointer;transition:opacity .15s,transform .1s;
      background:var(--plan-color);color:#fff;width:100%;
    }
    .ua-pm-btn:hover:not(:disabled){opacity:.85;transform:scale(.98)}
    .ua-pm-btn:disabled{background:#334155;color:#64748b;cursor:default}
    .ua-pm-loading {
      text-align:center;padding:40px;color:#94a3b8;
    }
    .ua-pm-success {
      text-align:center;padding:40px;
    }
    .ua-pm-success h2{color:#22c55e;font-size:24px;margin:0 0 8px}
    .ua-pm-success p{color:#94a3b8;font-size:14px;margin:0}
    .ua-pm-error-banner {
      background:#450a0a;border:1px solid #7f1d1d;border-radius:10px;
      padding:12px 16px;color:#fca5a5;font-size:13px;margin-bottom:16px;display:none;
    }
    @keyframes ua-fade-in{from{opacity:0}to{opacity:1}}
    @keyframes ua-slide-up{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
    @media(max-width:640px){
      #ua-premium-modal{padding:24px 16px;border-radius:20px}
      .ua-pm-grid{grid-template-columns:1fr 1fr}
    }
    @media(max-width:420px){
      .ua-pm-grid{grid-template-columns:1fr}
    }

    /* Upgrade banner in header */
    #ua-upgrade-cta {
      background:linear-gradient(135deg,#7c3aed,#2563eb);
      color:#fff;font-size:13px;font-weight:600;
      padding:8px 16px;border-radius:10px;border:none;cursor:pointer;
      display:inline-flex;align-items:center;gap:6px;
      transition:opacity .15s,transform .1s;white-space:nowrap;
    }
    #ua-upgrade-cta:hover{opacity:.9;transform:scale(.98)}

    /* Sticky promo bar */
    #ua-premium-bar {
      background:linear-gradient(90deg,#4c1d95 0%,#1d4ed8 100%);
      color:#fff;text-align:center;font-size:13px;font-weight:600;
      padding:10px 16px;display:flex;align-items:center;justify-content:center;gap:12px;
      position:relative;
    }
    #ua-premium-bar button {
      background:rgba(255,255,255,.2);border:1px solid rgba(255,255,255,.4);
      color:#fff;font-size:12px;font-weight:700;padding:4px 14px;border-radius:999px;
      cursor:pointer;transition:background .15s;
    }
    #ua-premium-bar button:hover{background:rgba(255,255,255,.35)}
    #ua-premium-bar-close {
      position:absolute;right:12px;background:none;border:none;color:rgba(255,255,255,.6);
      font-size:18px;cursor:pointer;line-height:1;padding:0;
    }
  `;

  // ── DOM Helpers ────────────────────────────────────────────────────────────
  function injectStyle() {
    if (document.getElementById('ua-premium-style')) return;
    var s = document.createElement('style');
    s.id = 'ua-premium-style';
    s.textContent = STYLE;
    document.head.appendChild(s);
  }

  function renderCard(plan) {
    var isPopular = plan.id === 'premium';
    var limits = plan.limits.map(function (l) {
      return '<li>' + l + '</li>';
    }).join('');
    var features = plan.features.map(function (f) {
      return '<li>' + f + '</li>';
    }).join('');
    return (
      '<div class="ua-pm-card' + (isPopular ? ' ua-pm-card--popular' : '') + (plan.disabled ? ' ua-pm-card--disabled' : '') + '" style="--plan-color:' + plan.color + '">' +
      (plan.badge ? '<div class="ua-pm-badge">' + plan.badge + '</div>' : '') +
      '<div class="ua-pm-name">' + plan.name + '</div>' +
      '<div class="ua-pm-price">' + (plan.price === 0 ? '₴0' : '₴' + plan.price) + '<span>/' + plan.period + '</span></div>' +
      '<ul class="ua-pm-features">' + features + '</ul>' +
      (limits ? '<ul class="ua-pm-features ua-pm-limits">' + limits + '</ul>' : '') +
      '<button class="ua-pm-btn" data-plan-id="' + plan.id + '"' + (plan.disabled ? ' disabled' : '') + '>' + plan.cta + '</button>' +
      '</div>'
    );
  }

  function buildModal() {
    var backdrop = document.createElement('div');
    backdrop.id = 'ua-premium-backdrop';
    backdrop.innerHTML = (
      '<div id="ua-premium-modal" role="dialog" aria-modal="true" aria-label="Преміум тарифи UA-Dim">' +
      '<button class="ua-pm-close" id="ua-pm-close-btn" aria-label="Закрити">×</button>' +
      '<h2 class="ua-pm-title">🏆 Преміум для власників і агентів</h2>' +
      '<p class="ua-pm-sub">Отримайте більше показів, ТОП-позицію та довіру покупців</p>' +
      '<div id="ua-pm-error" class="ua-pm-error-banner"></div>' +
      '<div class="ua-pm-grid" id="ua-pm-grid">' +
      PLANS.map(renderCard).join('') +
      '</div>' +
      '<p style="text-align:center;color:#475569;font-size:12px;margin-top:24px">Оплата через LiqPay · Захищено SSL · Скасування у будь-який момент</p>' +
      '</div>'
    );
    return backdrop;
  }

  // ── Payment flow ───────────────────────────────────────────────────────────
  function startPayment(planId) {
    var plan = PLANS.find(function (p) { return p.id === planId; });
    if (!plan || plan.disabled) return;

    var grid = document.getElementById('ua-pm-grid');
    var errBanner = document.getElementById('ua-pm-error');
    errBanner.style.display = 'none';

    grid.innerHTML = '<div class="ua-pm-loading">⏳ Підготовка оплати через LiqPay…</div>';

    var payload = {
      plan_id: plan.id,
      plan_name: plan.name,
      amount: plan.price,
      currency: 'UAH',
      description: 'UA-Dim ' + plan.name + ' — ' + plan.price + ' UAH/міс',
      result_url: window.location.origin + '/real-estate-demo.html?payment=success&plan=' + plan.id,
      server_url: API_BASE + '/api/payment/liqpay/callback',
    };

    fetch(API_BASE + '/api/payment/liqpay/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (resp) {
        if (resp.data && resp.signature) {
          // Submit LiqPay form
          var form = document.createElement('form');
          form.method = 'POST';
          form.action = 'https://www.liqpay.ua/api/3/checkout';
          form.style.display = 'none';
          ['data', 'signature'].forEach(function (key) {
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = key;
            input.value = resp[key];
            form.appendChild(input);
          });
          document.body.appendChild(form);
          // Track in GA4
          if (window.uaTrackInquiry) {
            window.uaTrackInquiry({ plan_id: plan.id, amount: plan.price });
          }
          if (window.dataLayer) {
            window.dataLayer.push({ event: 'premium_checkout_start', plan_id: plan.id, value: plan.price });
          }
          form.submit();
        } else if (resp.demo) {
          // Demo/sandbox mode — show success
          showSuccess(plan, true);
        } else {
          throw new Error(resp.error || 'Невідома помилка');
        }
      })
      .catch(function (err) {
        // Show error and restore grid
        grid.innerHTML = PLANS.map(renderCard).join('');
        bindCardButtons();
        errBanner.textContent = '⚠️ ' + (err.message || 'Помилка підключення до сервера оплати. Спробуйте пізніше.');
        errBanner.style.display = 'block';
        console.error('[UA Premium] Payment error:', err);
      });
  }

  function showSuccess(plan, isDemo) {
    var modal = document.getElementById('ua-premium-modal');
    if (!modal) return;
    modal.innerHTML = (
      '<div class="ua-pm-success">' +
      '<div style="font-size:56px;margin-bottom:16px">🎉</div>' +
      '<h2>' + (isDemo ? '⚙️ Тест-режим активовано' : '✅ Оплата успішна!') + '</h2>' +
      '<p>' + (isDemo ? 'LiqPay ключі не налаштовані — демо-режим' : 'Тариф «' + plan.name + '» підключено.') + '</p>' +
      '<p style="margin-top:8px">Деталі надіслані на вашу пошту</p>' +
      '<button onclick="document.getElementById(\'ua-premium-backdrop\').remove()" ' +
        'style="margin-top:24px;background:#22c55e;color:#fff;border:none;padding:12px 32px;border-radius:12px;font-weight:700;cursor:pointer;font-size:15px">Добре</button>' +
      '</div>'
    );
  }

  function bindCardButtons() {
    var buttons = document.querySelectorAll('#ua-pm-grid .ua-pm-btn:not(:disabled)');
    buttons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var planId = btn.getAttribute('data-plan-id');
        startPayment(planId);
      });
    });
  }

  // ── Open / Close Modal ─────────────────────────────────────────────────────
  function openModal() {
    if (document.getElementById('ua-premium-backdrop')) return;
    injectStyle();
    var modal = buildModal();
    document.body.appendChild(modal);
    bindCardButtons();

    document.getElementById('ua-pm-close-btn').addEventListener('click', closeModal);
    modal.addEventListener('click', function (e) {
      if (e.target === modal) closeModal();
    });
    document.addEventListener('keydown', onEsc);
    document.body.style.overflow = 'hidden';

    // Track open
    if (window.dataLayer) {
      window.dataLayer.push({ event: 'premium_modal_open' });
    }
  }

  function closeModal() {
    var el = document.getElementById('ua-premium-backdrop');
    if (el) el.remove();
    document.removeEventListener('keydown', onEsc);
    document.body.style.overflow = '';
  }

  function onEsc(e) {
    if (e.key === 'Escape') closeModal();
  }

  // ── Promo bar ──────────────────────────────────────────────────────────────
  function injectPromoBar() {
    if (document.getElementById('ua-premium-bar')) return;
    if (sessionStorage.getItem('ua-promo-bar-dismissed')) return;

    var bar = document.createElement('div');
    bar.id = 'ua-premium-bar';
    bar.innerHTML = (
      '<span>🚀 Отримайте ТОП-позицію — <strong>перший місяць зі знижкою 50%</strong></span>' +
      '<button onclick="window.uaPremium.open()">Дивитись тарифи</button>' +
      '<button id="ua-premium-bar-close" aria-label="Закрити">×</button>'
    );
    bar.querySelector('#ua-premium-bar-close').addEventListener('click', function () {
      bar.remove();
      sessionStorage.setItem('ua-promo-bar-dismissed', '1');
    });

    // Insert before root or as first child of body
    var root = document.getElementById('root') || document.body.firstElementChild;
    if (root && root.parentNode) {
      root.parentNode.insertBefore(bar, root);
    } else {
      document.body.prepend(bar);
    }
  }

  // ── Inject upgrade CTA into header ────────────────────────────────────────
  function injectUpgradeCTA() {
    // Try to find the add-listing button and add upgrade button near it
    var addBtn = Array.from(document.querySelectorAll('button')).find(function (b) {
      var t = b.textContent || '';
      return t.includes('Додати') || t.includes('додати');
    });
    if (!addBtn) return;
    if (document.getElementById('ua-upgrade-cta')) return;

    var btn = document.createElement('button');
    btn.id = 'ua-upgrade-cta';
    btn.innerHTML = '⭐ Преміум';
    btn.addEventListener('click', function () { window.uaPremium.open(); });

    injectStyle();
    addBtn.parentNode.insertBefore(btn, addBtn);
  }

  // ── Check payment result from URL ──────────────────────────────────────────
  function checkPaymentResult() {
    var params = new URLSearchParams(window.location.search);
    if (params.get('payment') === 'success') {
      var planId = params.get('plan') || '';
      var plan = PLANS.find(function (p) { return p.id === planId; }) || { name: 'Преміум', price: 0 };
      setTimeout(function () {
        openModal();
        showSuccess(plan, false);
      }, 800);
      // Track conversion
      if (window.dataLayer) {
        window.dataLayer.push({ event: 'premium_purchase', plan_id: planId, value: plan.price, currency: 'UAH' });
      }
      // Clean URL
      var url = new URL(window.location.href);
      url.searchParams.delete('payment');
      url.searchParams.delete('plan');
      history.replaceState({}, '', url.toString());
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  window.uaPremium = {
    open: openModal,
    close: closeModal,
    plans: PLANS,
  };

  // ── Init ───────────────────────────────────────────────────────────────────
  function init() {
    injectStyle();
    // Defer non-critical init
    if ('requestIdleCallback' in window) {
      requestIdleCallback(function () {
        setTimeout(injectPromoBar, 2000);
        injectUpgradeCTA();
        checkPaymentResult();
      }, { timeout: 3000 });
    } else {
      setTimeout(function () {
        injectPromoBar();
        injectUpgradeCTA();
        checkPaymentResult();
      }, 2000);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
