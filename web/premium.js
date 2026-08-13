/**
 * UA-Dim Premium Tiers — Pricing modal + LiqPay payment flow
 * Автоматично підключається до backend /api/payment/liqpay/create
 */
(function () {
  'use strict';

  var resolveApiBase = function () {
    var configured = (typeof window !== 'undefined' && window.UA_HOMES_API ? window.UA_HOMES_API : '').toString().trim();
    if (configured && configured !== '__UA_HOMES_API__') return configured.replace(/\/+$/, '');
    if (typeof window !== 'undefined' && (window.location.protocol === 'file:' || ['localhost', '127.0.0.1'].includes(window.location.hostname))) {
      return 'http://localhost:5050';
    }
    if (typeof window !== 'undefined') {
      return window.location.origin;
    }
    return 'http://localhost:5050';
  };

  var API_BASE = resolveApiBase();
  var PROMO_DISMISSED_UNTIL_KEY = 'ua-promo-bar-dismissed-until';
  var PROMO_SESSION_HIDDEN_KEY = 'ua-promo-bar-hidden-session';
  var PROMO_DISMISS_DURATION_MS = 30 * 24 * 60 * 60 * 1000;
  var lastFocusedElement = null;
  var previousBodyOverflow = '';
  var buildApiUrl = function (path) {
    return `${API_BASE}/api${path}`;
  };

  // ── Тарифи ────────────────────────────────────────────────────────────────
  // Ідентифікатори мають збігатися з SUBSCRIPTION_PLANS у backend/app.py.
  var PLANS = [
    {
      id: 'free',
      audience: 'owner',
      name: 'Базовий',
      price: 0,
      period: 'безкоштовно',
      badge: null,
      color: '#64748b',
      features: [
        '1 оголошення',
        '30 днів активності',
        'Стандартна позиція',
      ],
      limits: ['Без виділення', 'Без ТОП-позиції'],
      cta: 'Доступний одразу',
      disabled: true,
    },
    {
      id: 'standard',
      audience: 'owner',
      name: 'Стандарт',
      price: 299,
      period: 'міс',
      badge: null,
      color: '#2563eb',
      features: [
        '5 оголошень',
        '60 днів активності',
        'Виділення в пошуку',
        'Статистика переглядів',
      ],
      limits: ['Без ТОП-позиції'],
      cta: 'Підключити',
      disabled: false,
    },
    {
      id: 'premium',
      audience: 'owner',
      name: 'Преміум',
      price: 699,
      period: 'міс',
      badge: '🔥 Популярний',
      color: '#7c3aed',
      features: [
        '15 оголошень',
        '90 днів активності',
        'ТОП-позиція в пошуку',
        'Бейдж «Перевірено»',
        'Детальна аналітика',
      ],
      limits: [],
      cta: 'Підключити',
      disabled: false,
    },
    {
      id: 'realtor_free',
      audience: 'realtor',
      name: 'Ріелтор Базовий',
      price: 0,
      period: 'безкоштовно',
      badge: null,
      color: '#64748b',
      features: [
        '3 оголошення',
        '30 днів активності',
        'Профіль ріелтора',
      ],
      limits: ['Без виділення', 'Без ТОП-позиції'],
      cta: 'Доступний одразу',
      disabled: true,
    },
    {
      id: 'realtor_start',
      audience: 'realtor',
      name: 'Ріелтор Старт',
      price: 799,
      period: 'міс',
      badge: null,
      color: '#0f766e',
      features: [
        '30 оголошень',
        'Профіль ріелтора',
        'Виділення в пошуку',
        'Статистика переглядів',
      ],
      limits: ['Без ТОП-позиції'],
      cta: 'Підключити',
      disabled: false,
    },
    {
      id: 'realtor_pro',
      audience: 'realtor',
      name: 'Ріелтор Про',
      price: 1499,
      period: 'міс',
      badge: '🔥 Популярний',
      color: '#b45309',
      features: [
        '100 оголошень',
        'ТОП-позиція в пошуку',
        'Бейдж «Перевірено»',
        'Детальна аналітика',
        'Пріоритетна підтримка',
      ],
      limits: [],
      cta: 'Підключити',
      disabled: false,
    },
    {
      id: 'realtor_agency',
      audience: 'realtor',
      name: 'Агенція',
      price: 2999,
      period: 'міс',
      badge: '🏢 Для команд',
      color: '#1d4ed8',
      features: [
        'Необмежено оголошень',
        'Брендинг агентства',
        'API доступ',
        'CRM-інтеграція',
        'Верифікація агентства',
        'Особистий менеджер',
      ],
      limits: [],
      cta: 'Підключити',
      disabled: false,
    },
  ];

  var AUDIENCES = [
    { id: 'owner', label: '🏠 Власник', hint: 'Продаю або здаю власне житло' },
    { id: 'realtor', label: '🤝 Ріелтор', hint: 'Працюю з клієнтами та об\'єктами' },
  ];

  // Старі посилання на тариф «agent» ведуть на «Ріелтор Про».
  var LEGACY_PLAN_ALIASES = { agent: 'realtor_pro' };

  var activeAudience = 'owner';

  function resolvePlanId(planId) {
    return LEGACY_PLAN_ALIASES[planId] || planId;
  }

  function findPlan(planId) {
    var wanted = resolvePlanId(planId);
    return PLANS.find(function (p) { return p.id === wanted; });
  }

  function plansForAudience(audience) {
    return PLANS.filter(function (p) { return p.audience === audience; });
  }

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
      color:#cbd5e1;font-size:22px;cursor:pointer;line-height:1;padding:4px;
      min-width:44px;min-height:44px;
    }
    .ua-pm-close:hover{color:#f1f5f9}
    .ua-pm-title {
      font-size:clamp(18px,3vw,26px);font-weight:800;color:#f1f5f9;
      text-align:center;margin:0 0 6px;
    }
    .ua-pm-sub {
      text-align:center;color:#cbd5e1;font-size:14px;margin:0 0 20px;
    }
    .ua-pm-tabs {
      display:flex;gap:10px;justify-content:center;margin:0 0 24px;flex-wrap:wrap;
    }
    .ua-pm-tab {
      display:flex;flex-direction:column;align-items:center;gap:2px;cursor:pointer;
      background:#1e293b;border:1.5px solid #334155;border-radius:14px;
      padding:10px 20px;color:#cbd5e1;transition:border-color .2s,background .2s,color .2s;
      font:inherit;min-width:180px;
    }
    .ua-pm-tab:hover{border-color:#64748b}
    .ua-pm-tab--active{background:#2563eb;border-color:#2563eb;color:#fff}
    .ua-pm-tab-label{font-size:15px;font-weight:700}
    .ua-pm-tab-hint{font-size:11px;opacity:1}
    .ua-pm-tab--active .ua-pm-tab-hint{color:#fff}
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
    .ua-pm-card--disabled{border-style:dashed}
    .ua-pm-badge {
      position:absolute;top:-12px;left:50%;transform:translateX(-50%);
      background:var(--plan-color);color:#fff;font-size:11px;font-weight:700;
      padding:3px 12px;border-radius:999px;white-space:nowrap;
    }
    .ua-pm-name {font-size:13px;font-weight:700;color:#cbd5e1;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}
    .ua-pm-price {font-size:32px;font-weight:900;color:#f1f5f9;line-height:1}
    .ua-pm-price span {font-size:14px;font-weight:500;color:#cbd5e1}
    .ua-pm-features {list-style:none;padding:0;margin:16px 0;display:flex;flex-direction:column;gap:8px;flex:1}
    .ua-pm-features li {font-size:13px;color:#cbd5e1;display:flex;gap:8px;align-items:flex-start}
    .ua-pm-features li::before {content:"✓";color:#22c55e;font-weight:700;flex-shrink:0}
    .ua-pm-limits li::before {content:"–";color:#ef4444}
    .ua-pm-limits li {color:#cbd5e1}
    .ua-pm-btn {
      margin-top:auto;padding:12px;border-radius:12px;font-weight:700;font-size:14px;
      border:none;cursor:pointer;transition:opacity .15s,transform .1s;min-height:44px;
      background:var(--plan-color);color:#fff;width:100%;
    }
    .ua-pm-btn:hover:not(:disabled){opacity:.85;transform:scale(.98)}
    .ua-pm-btn:disabled{background:#475569;color:#f8fafc;cursor:default}
    .ua-pm-loading {
      text-align:center;padding:40px;color:#cbd5e1;
    }
    .ua-pm-success {
      text-align:center;padding:40px;
    }
    .ua-pm-success h2{color:#22c55e;font-size:24px;margin:0 0 8px}
    .ua-pm-success p{color:#cbd5e1;font-size:14px;margin:0}
    .ua-pm-error-banner {
      background:#450a0a;border:1px solid #7f1d1d;border-radius:10px;
      padding:12px 16px;color:#fca5a5;font-size:13px;margin-bottom:16px;display:none;
    }
    #ua-premium-modal button:focus-visible,
    #ua-premium-modal a:focus-visible {
      outline:3px solid #93c5fd;outline-offset:3px;
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
      display:inline-flex;align-items:center;gap:6px;min-height:44px;
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
      cursor:pointer;transition:background .15s;min-height:44px;min-width:44px;
    }
    #ua-premium-bar button:hover{background:rgba(255,255,255,.35)}
    #ua-premium-bar button:focus-visible{outline:3px solid rgba(255,255,255,.85);outline-offset:2px}
    #ua-premium-bar-close {
      position:absolute;right:12px;background:none;border:none;color:rgba(255,255,255,.6);
      font-size:18px;cursor:pointer;line-height:1;padding:0;
    }
    @media(max-width:640px){
      #ua-premium-bar {
        justify-content:flex-start;text-align:left;font-size:11px;line-height:1.35;
        padding:7px 72px 7px 12px;gap:8px;
      }
      #ua-premium-bar button {
        padding:3px 9px;font-size:11px;flex-shrink:0;
      }
      #ua-premium-bar-close {
        right:8px;font-size:16px;
      }
    }
    @media(prefers-reduced-motion:reduce){
      #ua-premium-backdrop,#ua-premium-modal,#ua-premium-modal *,#ua-premium-bar,#ua-premium-bar *{
        animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important;
      }
      .ua-pm-card:hover:not(.ua-pm-card--disabled),.ua-pm-btn:hover:not(:disabled),#ua-upgrade-cta:hover{
        transform:none;
      }
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
    var isPopular = plan.badge === '🔥 Популярний';
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
      '<button class="ua-pm-btn" data-plan-id="' + plan.id + '" aria-label="' + plan.cta + ' — тариф ' + plan.name + '"' + (plan.disabled ? ' disabled' : '') + '>' + plan.cta + '</button>' +
      '</div>'
    );
  }

  function renderGrid() {
    return plansForAudience(activeAudience).map(renderCard).join('');
  }

  function renderAudienceTabs() {
    return (
      '<div class="ua-pm-tabs" role="group" aria-label="Тип користувача">' +
      AUDIENCES.map(function (a) {
        return (
          '<button class="ua-pm-tab' + (a.id === activeAudience ? ' ua-pm-tab--active' : '') + '"' +
          ' aria-pressed="' + (a.id === activeAudience) + '" data-audience="' + a.id + '">' +
          '<span class="ua-pm-tab-label">' + a.label + '</span>' +
          '<span class="ua-pm-tab-hint">' + a.hint + '</span>' +
          '</button>'
        );
      }).join('') +
      '</div>'
    );
  }

  function refreshGrid() {
    var tabs = document.querySelector('.ua-pm-tabs');
    var grid = document.getElementById('ua-pm-grid');
    if (!grid) return;
    if (tabs) tabs.outerHTML = renderAudienceTabs();
    document.getElementById('ua-pm-grid').innerHTML = renderGrid();
    bindAudienceTabs();
    bindCardButtons();
  }

  function bindAudienceTabs() {
    var tabs = document.querySelectorAll('.ua-pm-tab');
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        var next = tab.getAttribute('data-audience');
        if (!next || next === activeAudience) return;
        activeAudience = next;
        refreshGrid();
      });
    });
  }

  function buildModal() {
    var backdrop = document.createElement('div');
    backdrop.id = 'ua-premium-backdrop';
    backdrop.innerHTML = (
      '<div id="ua-premium-modal" role="dialog" aria-modal="true" aria-labelledby="ua-pm-title" aria-describedby="ua-pm-description">' +
      '<button class="ua-pm-close" id="ua-pm-close-btn" aria-label="Закрити">×</button>' +
      '<h2 class="ua-pm-title" id="ua-pm-title">🏆 Тарифи UA-Dim</h2>' +
      '<p class="ua-pm-sub" id="ua-pm-description">Окремі пакети для власників житла та ріелторів</p>' +
      renderAudienceTabs() +
      '<div id="ua-pm-error" class="ua-pm-error-banner" role="alert"></div>' +
      '<div class="ua-pm-grid" id="ua-pm-grid">' +
      renderGrid() +
      '</div>' +
      '<p style="text-align:center;color:#cbd5e1;font-size:12px;margin-top:24px">Оплата через LiqPay · Захищено SSL · Скасування у будь-який момент</p>' +
      '</div>'
    );
    return backdrop;
  }

  // ── Payment flow ───────────────────────────────────────────────────────────
  function getAuthToken() {
    return (window.localStorage.getItem('uaDim.authToken') || '').trim();
  }

  function escapeHtml(value) {
    var node = document.createElement('div');
    node.textContent = String(value == null ? '' : value);
    return node.innerHTML;
  }

  function startPayment(planId) {
    var plan = findPlan(planId);
    if (!plan || plan.disabled) return;

    var grid = document.getElementById('ua-pm-grid');
    var errBanner = document.getElementById('ua-pm-error');
    errBanner.style.display = 'none';
    var token = getAuthToken();
    if (!token) {
      errBanner.textContent = '⚠️ Увійдіть в обліковий запис перед оплатою тарифу.';
      errBanner.style.display = 'block';
      return;
    }

    grid.innerHTML = '<div class="ua-pm-loading" role="status" aria-live="polite">⏳ Підготовка оплати через LiqPay…</div>';

    var payload = {
      plan_id: plan.id,
    };

    fetch(buildApiUrl('/payment/liqpay/create'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': ['Bearer', token].join(' '),
      },
      credentials: 'include',
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (resp) {
          if (!r.ok) throw new Error(resp.error || 'HTTP ' + r.status);
          return resp;
        });
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
        } else {
          throw new Error(resp.error || 'Невідома помилка');
        }
      })
      .catch(function (err) {
        // Show error and restore grid
        grid.innerHTML = renderGrid();
        bindCardButtons();
        errBanner.textContent = '⚠️ ' + (err.message || 'Помилка підключення до сервера оплати. Спробуйте пізніше.');
        errBanner.style.display = 'block';
        console.error('[UA Premium] Payment error:', err);
        });
  }

  function showSuccess(plan, isSandbox) {
    var modal = document.getElementById('ua-premium-modal');
    if (!modal) return;
    modal.innerHTML = (
        '<div class="ua-pm-success" role="status" aria-live="polite">' +
        '<div style="font-size:56px;margin-bottom:16px">🎉</div>' +
        '<h2>' + (isSandbox ? '⚙️ Тестову оплату підтверджено' : '✅ Оплата успішна!') + '</h2>' +
        '<p>Тариф «' + escapeHtml(plan.name) + '» підключено.</p>' +
        '<button id="ua-pm-success-close" ' +
        'style="margin-top:24px;background:#15803d;color:#fff;border:none;padding:12px 32px;border-radius:12px;font-weight:700;cursor:pointer;font-size:15px;min-height:44px">Добре</button>' +
        '</div>'
    );
    document.getElementById('ua-pm-success-close').addEventListener('click', closeModal);
    document.getElementById('ua-pm-success-close').focus();
  }

  function showPaymentState(title, message, isError) {
    var modal = document.getElementById('ua-premium-modal');
    if (!modal) return;
    modal.innerHTML = (
      '<div class="ua-pm-success" role="' + (isError ? 'alert' : 'status') + '" aria-live="polite">' +
      '<div style="font-size:48px;margin-bottom:16px">' + (isError ? '⚠️' : '⏳') + '</div>' +
      '<h2 style="color:' + (isError ? '#fca5a5' : '#f1f5f9') + '">' + escapeHtml(title) + '</h2>' +
      '<p>' + escapeHtml(message) + '</p>' +
      '<button id="ua-pm-success-close" ' +
      'style="margin-top:24px;background:#2563eb;color:#fff;border:none;padding:12px 32px;border-radius:12px;font-weight:700;cursor:pointer;font-size:15px;min-height:44px">Закрити</button>' +
      '</div>'
    );
    document.getElementById('ua-pm-success-close').addEventListener('click', closeModal);
    document.getElementById('ua-pm-success-close').focus();
  }

  function pollPaymentStatus(orderId, token, attemptsLeft) {
    fetch(buildApiUrl('/payment/orders/' + encodeURIComponent(orderId)), {
      headers: { 'Authorization': ['Bearer', token].join(' ') },
      credentials: 'include',
    })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (resp) {
          if (!r.ok) throw new Error(resp.error || 'Не вдалося перевірити оплату');
          return resp;
        });
      })
      .then(function (resp) {
        var plan = findPlan(resp.plan_id) || { name: 'Преміум', price: 0 };
        if (resp.paid) {
          showSuccess(plan, resp.environment === 'sandbox');
          if (resp.environment === 'live' && window.dataLayer) {
            window.dataLayer.push({
              event: 'premium_purchase',
              plan_id: resp.plan_id,
              value: resp.amount,
              currency: resp.currency,
            });
          }
          return;
        }
        if (resp.status === 'failed' || resp.status === 'rejected') {
          showPaymentState('Оплату не підтверджено', 'Тариф не активовано. Кошти не повинні бути зараховані як успішна оплата.', true);
          return;
        }
        if (attemptsLeft > 0) {
          window.setTimeout(function () {
            pollPaymentStatus(orderId, token, attemptsLeft - 1);
          }, 1500);
          return;
        }
        showPaymentState('Оплата обробляється', 'Підтвердження від LiqPay ще не отримано. Перевірте статус тарифу пізніше.', false);
      })
      .catch(function (error) {
        showPaymentState('Не вдалося перевірити оплату', error.message || 'Спробуйте пізніше.', true);
      });
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
  function openModal(audience) {
    if (audience === 'owner' || audience === 'realtor') {
      activeAudience = audience;
    }
    if (document.getElementById('ua-premium-backdrop')) {
      refreshGrid();
      return;
    }
    injectStyle();
    lastFocusedElement = document.activeElement;
    var modal = buildModal();
    document.body.appendChild(modal);
    bindAudienceTabs();
    bindCardButtons();

    document.getElementById('ua-pm-close-btn').addEventListener('click', closeModal);
    modal.addEventListener('click', function (e) {
      if (e.target === modal) closeModal();
    });
    document.addEventListener('keydown', onModalKeydown);
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.requestAnimationFrame(function () {
      document.getElementById('ua-pm-close-btn').focus();
    });

    // Track open
    if (window.dataLayer) {
      window.dataLayer.push({ event: 'premium_modal_open', audience: activeAudience });
    }
  }

  function closeModal() {
    var el = document.getElementById('ua-premium-backdrop');
    if (el) el.remove();
    document.removeEventListener('keydown', onModalKeydown);
    document.body.style.overflow = previousBodyOverflow;
    if (lastFocusedElement && document.contains(lastFocusedElement)) lastFocusedElement.focus();
    lastFocusedElement = null;
  }

  function onModalKeydown(e) {
    if (e.key === 'Escape') {
      closeModal();
      return;
    }
    if (e.key !== 'Tab') return;
    var modal = document.getElementById('ua-premium-modal');
    if (!modal) return;
    var focusable = Array.from(
      modal.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')
    ).filter(function (element) { return element.getClientRects().length > 0; });
    if (!focusable.length) return;
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  // ── Promo bar ──────────────────────────────────────────────────────────────
  function promoDismissed() {
    if (
      sessionStorage.getItem(PROMO_SESSION_HIDDEN_KEY) ||
      sessionStorage.getItem('ua-promo-bar-dismissed')
    ) return true;
    var dismissedUntil = Number(localStorage.getItem(PROMO_DISMISSED_UNTIL_KEY));
    return Number.isFinite(dismissedUntil) && dismissedUntil > Date.now();
  }

  function injectPromoBar() {
    if (document.getElementById('ua-premium-bar')) return;
    if (promoDismissed()) return;
    sessionStorage.setItem(PROMO_SESSION_HIDDEN_KEY, 'shown');

    var bar = document.createElement('div');
    bar.id = 'ua-premium-bar';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', 'Пропозиція тарифів UA-Dim');
    bar.setAttribute('aria-live', 'polite');
    bar.innerHTML = (
      '<span>🚀 Отримайте ТОП-позицію — <strong>перший місяць зі знижкою 50%</strong></span>' +
      '<button id="ua-premium-bar-open">Дивитись тарифи</button>' +
      '<button id="ua-premium-bar-close" aria-label="Закрити">×</button>'
    );
    bar.querySelector('#ua-premium-bar-open').addEventListener('click', function () {
      window.uaPremium.open();
    });
    bar.querySelector('#ua-premium-bar-close').addEventListener('click', function () {
      bar.remove();
      sessionStorage.setItem(PROMO_SESSION_HIDDEN_KEY, 'dismissed');
      localStorage.setItem(PROMO_DISMISSED_UNTIL_KEY, String(Date.now() + PROMO_DISMISS_DURATION_MS));
    });

    // Keep promotional content outside the initial hero viewport.
    var root = document.getElementById('root') || document.body.firstElementChild;
    if (root && root.parentNode) {
      root.parentNode.insertBefore(bar, root.nextSibling);
    } else {
      document.body.appendChild(bar);
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
    var paymentResult = params.get('payment');
    if (!paymentResult) return;
    var orderId = params.get('order_id') || '';
    var token = getAuthToken();

    var url = new URL(window.location.href);
    url.searchParams.delete('payment');
    url.searchParams.delete('plan');
    url.searchParams.delete('order_id');
    history.replaceState({}, '', url.toString());

    if (paymentResult !== 'return' || !orderId) return;
    setTimeout(function () {
      openModal();
      if (!token) {
        showPaymentState('Потрібна авторизація', 'Увійдіть, щоб перевірити статус оплати.', true);
        return;
      }
      showPaymentState('Перевіряємо оплату', 'Очікуємо підтвердження від LiqPay…', false);
      pollPaymentStatus(orderId, token, 6);
    }, 400);
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  window.uaPremium = {
    open: openModal,
    close: closeModal,
    plans: PLANS,
    plansFor: plansForAudience,
  };

  // ── Init ───────────────────────────────────────────────────────────────────
  function init() {
    injectStyle();
    checkPaymentResult();
    if (promoDismissed()) return;

    var revealPromo = function () {
      injectPromoBar();
      window.removeEventListener('uah:meaningful-interaction', revealPromo);
      window.removeEventListener('scroll', onScroll);
    };
    var onScroll = function () {
      if (window.scrollY < Math.max(320, window.innerHeight * 0.55)) return;
      revealPromo();
    };
    window.addEventListener('uah:meaningful-interaction', revealPromo, { once: true });
    window.addEventListener('scroll', onScroll, { passive: true });
    if (window.scrollY >= Math.max(320, window.innerHeight * 0.55)) {
      revealPromo();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
