/**
 * UA-Dim Analytics — GTM + GA4 Integration
 *
 * ─────────────────────────────────────────────────────────────────
 * ⚙️  НАЛАШТУВАННЯ:
 *
 *  1. Зайдіть на https://tagmanager.google.com/ → "Створити акаунт"
 *     Платформа: Web | URL: ua-dim.com → Отримайте GTM-KVWMVQGM
 *
 *  2. Зайдіть на https://analytics.google.com/ → "Додати ресурс"
 *     Отримайте G-LJSB794FJK (Measurement ID)
 *
 *  3. Замініть рядки нижче:
 *     GTM_CONTAINER_ID = 'GTM-KVWMVQGM'    ← ваш GTM ID
 *     GA4_MEASUREMENT_ID = 'G-LJSB794FJK' ← ваш GA4 ID
 *
 * ─────────────────────────────────────────────────────────────────
 */

(function () {
  'use strict';

  // ── IDs (замініть на реальні після реєстрації в GTM/GA4) ──
  var GTM_CONTAINER_ID  = 'GTM-KVWMVQGM';
  var GA4_MEASUREMENT_ID = 'G-LJSB794FJK';

  var IS_CONFIGURED = GTM_CONTAINER_ID.startsWith('GTM-') && GA4_MEASUREMENT_ID.startsWith('G-');
  var IS_DEV = location.hostname === 'localhost' || location.hostname === '127.0.0.1';

  // ── dataLayer init (GTM standard) ──────────────────────────────
  window.dataLayer = window.dataLayer || [];

  // ── gtag helper ────────────────────────────────────────────────
  function gtag() {
    window.dataLayer.push(arguments);
  }
  window.gtag = window.gtag || gtag;

  // ── Load GTM (async, non-blocking) ────────────────────────────
  function loadGTM() {
    if (!IS_CONFIGURED) return;
    (function (w, d, s, l, i) {
      w[l] = w[l] || [];
      w[l].push({ 'gtm.start': new Date().getTime(), event: 'gtm.js' });
      var f = d.getElementsByTagName(s)[0];
      var j = d.createElement(s);
      var dl = l !== 'dataLayer' ? '&l=' + l : '';
      j.async = true;
      j.src = 'https://www.googletagmanager.com/gtm.js?id=' + i + dl;
      f.parentNode.insertBefore(j, f);
    })(window, document, 'script', 'dataLayer', GTM_CONTAINER_ID);
  }

  // ── Load GA4 directly (fallback if no GTM) ───────────────────
  function loadGA4() {
    if (!IS_CONFIGURED) return;
    var s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + GA4_MEASUREMENT_ID;
    document.head.appendChild(s);

    gtag('js', new Date());
    gtag('config', GA4_MEASUREMENT_ID, {
      page_location: location.href,
      page_title: document.title,
      send_page_view: true,
      debug_mode: IS_DEV,
      // Consent defaults (GDPR-aware)
      ads_storage: 'denied',
      analytics_storage: 'granted'
    });
  }

  // ── Universal event tracker ────────────────────────────────────
  function track(eventName, params) {
    var payload = Object.assign({ event_source: 'ua_dim' }, params || {});

    // GA4 via gtag
    if (IS_CONFIGURED) {
      gtag('event', eventName, payload);
    }

    // Push to dataLayer (for GTM triggers too)
    window.dataLayer.push(Object.assign({ event: 'ua_' + eventName }, payload));

    // Dev console debug
    if (IS_DEV) {
      console.debug('[UA Analytics]', eventName, payload);
    }
  }
  window.uaTrack = track;

  // ── Key conversion events (called by app or listeners below) ──

  // Перегляд картки оголошення
  window.uaTrackListingView = function (listing) {
    track('listing_view', {
      listing_id: listing.id,
      listing_city: listing.city,
      listing_type: listing.listing_type || 'sale',
      listing_price: listing.price,
      listing_rooms: listing.rooms,
      e_oselya: listing.eOselya ? 'yes' : 'no',
      value: listing.price,
      currency: 'USD'
    });
  };

  // Показ телефону (ВИСОКА конверсія)
  window.uaTrackPhoneReveal = function (listingId, source) {
    track('phone_reveal', {
      listing_id: listingId,
      source: source || 'detail_modal',
      conversion_type: 'contact'
    });
  };

  // Додавання до обраних
  window.uaTrackSave = function (listingId, city) {
    track('listing_save', {
      listing_id: listingId,
      listing_city: city,
      conversion_type: 'engagement'
    });
  };

  // Пошук/фільтрація
  window.uaTrackSearch = function (params) {
    track('search_performed', {
      search_city: params.city || 'all',
      search_rooms: params.rooms,
      search_price_min: params.priceMin,
      search_price_max: params.priceMax,
      e_oselya_filter: params.eOselya ? 'yes' : 'no',
      listing_type: params.listingType || 'all'
    });
  };

  // Відкриття карти
  window.uaTrackMapOpen = function () {
    track('map_view', { ui_action: 'open_map' });
  };

  // Заявка/лід
  window.uaTrackInquiry = function (listingId, source) {
    track('listing_inquiry', {
      listing_id: listingId,
      source: source || 'detail_modal',
      conversion_type: 'lead',
      value: 1
    });
  };

  // Іпотечний калькулятор
  window.uaTrackMortgage = function (bankName, amount) {
    track('mortgage_calc', {
      bank_name: bankName,
      loan_amount: amount
    });
  };

  // ── Intercept existing dataLayer pushes from real-estate-app.js ─
  // The app already pushes {event:'uah_lead_funnel', ...} to dataLayer.
  // We proxy those into GA4 events.
  var _origPush = window.dataLayer.push.bind(window.dataLayer);
  window.dataLayer.push = function () {
    for (var i = 0; i < arguments.length; i++) {
      var item = arguments[i];
      if (item && item.event === 'uah_lead_funnel' && IS_CONFIGURED) {
        gtag('event', 'lead_funnel_' + (item.action || 'event'), {
          funnel_action: item.action,
          funnel_intent: item.intent,
          funnel_source: item.source,
          listing_id: item.listing_id
        });
      }
    }
    return _origPush.apply(window.dataLayer, arguments);
  };

  // ── Event delegation: key UI interactions ──────────────────────
  document.addEventListener('click', function (e) {
    var target = e.target;

    // Кнопка "Показати телефон"
    if (target.closest && target.closest('[data-action="show-phone"]')) {
      var btn = target.closest('[data-action="show-phone"]');
      window.uaTrackPhoneReveal(btn.dataset.listingId || 'unknown', 'card_click');
      return;
    }

    // Кнопка "Зберегти / серце" (favorites)
    if (target.closest && target.closest('[data-action="toggle-favorite"]')) {
      var fBtn = target.closest('[data-action="toggle-favorite"]');
      window.uaTrackSave(fBtn.dataset.listingId || 'unknown', fBtn.dataset.city);
      return;
    }

    // Кнопка відкриття карти
    if (target.closest && target.closest('[data-action="open-map"]')) {
      window.uaTrackMapOpen();
      return;
    }
  }, false);

  // ── єОселя checkbox ───────────────────────────────────────────
  document.addEventListener('change', function (e) {
    if (e.target && e.target.id === 'eoselya') {
      track('eoselya_filter', { enabled: e.target.checked });
    }
  }, false);

  // ── Track SPA-style navigation (hash or URL changes) ─────────
  var lastPath = location.pathname + location.search;
  function checkPageChange() {
    var current = location.pathname + location.search;
    if (current !== lastPath) {
      lastPath = current;
      if (IS_CONFIGURED) {
        gtag('event', 'page_view', {
          page_location: location.href,
          page_title: document.title
        });
      }
    }
  }
  window.addEventListener('popstate', checkPageChange);
  window.addEventListener('hashchange', checkPageChange);

  // Intercept pushState / replaceState for SPA navigation
  ['pushState', 'replaceState'].forEach(function (method) {
    var orig = history[method];
    history[method] = function () {
      orig.apply(history, arguments);
      setTimeout(checkPageChange, 100);
    };
  });

  // ── Web Vitals → GA4 ─────────────────────────────────────────
  // Requires web-vitals library loaded externally, or uses PerformanceObserver
  function observeLCP() {
    if (!IS_CONFIGURED || !window.PerformanceObserver) return;
    try {
      var po = new PerformanceObserver(function (list) {
        var entries = list.getEntries();
        var last = entries[entries.length - 1];
        if (last) {
          gtag('event', 'web_vitals', {
            metric_name: 'LCP',
            metric_value: Math.round(last.startTime),
            metric_rating: last.startTime < 2500 ? 'good' : last.startTime < 4000 ? 'needs_improvement' : 'poor'
          });
        }
      });
      po.observe({ type: 'largest-contentful-paint', buffered: true });
    } catch (e) { /* noop */ }
  }

  // ── Init ──────────────────────────────────────────────────────
  function init() {
    // Prefer GTM (manages GA4 inside); load GA4 directly only if no GTM
    if (IS_CONFIGURED) {
      loadGTM();
      // GA4 direct as fallback — GTM will also fire it, but gtag config ensures
      // events go through even before GTM container loads
      loadGA4();
    } else {
      // Not configured: still wire up dataLayer for when IDs are added
      if (IS_DEV) {
        console.info('[UA Analytics] Not configured. Replace GTM_CONTAINER_ID and GA4_MEASUREMENT_ID in analytics.js');
      }
    }

    // Always observe vitals (data goes to backend telemetry even without GA4)
    window.addEventListener('load', observeLCP, { once: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
