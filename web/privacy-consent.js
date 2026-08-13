(function () {
  'use strict';

  var STORAGE_KEY = 'uaDim.privacyConsent.v1';
  var GA_MEASUREMENT_ID = 'G-LJSB794FJK';
  var currentState = readState();
  var returnFocusTo = null;

  function defaultState() {
    return {
      version: 1,
      decided: false,
      necessary: true,
      analytics: false,
      updatedAt: null
    };
  }

  function readState() {
    try {
      var parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
      if (parsed && parsed.version === 1 && typeof parsed.analytics === 'boolean') {
        return {
          version: 1,
          decided: true,
          necessary: true,
          analytics: parsed.analytics,
          updatedAt: parsed.updatedAt || null
        };
      }
    } catch (_error) {}
    return defaultState();
  }

  function analyticsAllowed() {
    return currentState.decided && currentState.analytics;
  }

  function persistState() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(currentState));
    } catch (_error) {}
  }

  function updateGoogleConsent() {
    window['ga-disable-' + GA_MEASUREMENT_ID] = !analyticsAllowed();
    if (!analyticsAllowed()) {
      document.cookie.split(';').forEach(function (entry) {
        var name = entry.split('=')[0].trim();
        if (!/^_ga(?:_|$)/.test(name)) return;
        document.cookie = name + '=; Max-Age=0; path=/; SameSite=Lax';
        document.cookie = name + '=; Max-Age=0; path=/; domain=.' + window.location.hostname + '; SameSite=Lax';
      });
    }
    if (typeof window.gtag === 'function') {
      window.gtag('consent', 'update', {
        ad_storage: 'denied',
        ad_user_data: 'denied',
        ad_personalization: 'denied',
        analytics_storage: analyticsAllowed() ? 'granted' : 'denied'
      });
    }
  }

  function setConsent(analytics, source) {
    var previousAnalytics = analyticsAllowed();
    currentState = {
      version: 1,
      decided: true,
      necessary: true,
      analytics: Boolean(analytics),
      updatedAt: new Date().toISOString()
    };
    persistState();
    updateGoogleConsent();
    renderBanner();
    closeSettings();
    window.dispatchEvent(new CustomEvent('ua:consent-change', {
      detail: {
        analytics: analyticsAllowed(),
        previousAnalytics: previousAnalytics,
        source: source || 'preferences'
      }
    }));
  }

  function renderBanner() {
    var banner = document.getElementById('ua-privacy-banner');
    if (banner) banner.hidden = currentState.decided;
  }

  function openSettings(trigger) {
    var dialog = document.getElementById('ua-privacy-dialog');
    var checkbox = document.getElementById('ua-consent-analytics');
    if (!dialog || !checkbox) return;
    returnFocusTo = trigger || document.activeElement;
    checkbox.checked = analyticsAllowed();
    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
    }
    window.setTimeout(function () {
      checkbox.focus();
    }, 0);
  }

  function closeSettings() {
    var dialog = document.getElementById('ua-privacy-dialog');
    if (!dialog || !dialog.hasAttribute('open')) return;
    if (typeof dialog.close === 'function') {
      dialog.close();
    } else {
      dialog.removeAttribute('open');
    }
  }

  function buildInterface() {
    if (!document.body || document.getElementById('ua-privacy-banner')) return;

    var banner = document.createElement('section');
    banner.id = 'ua-privacy-banner';
    banner.className = 'ua-privacy-banner';
    banner.setAttribute('aria-labelledby', 'ua-privacy-title');
    banner.innerHTML =
      '<div class="ua-privacy-banner__content">' +
        '<div>' +
          '<h2 id="ua-privacy-title">Ваш вибір приватності</h2>' +
          '<p>UA-Dim використовує необхідне сховище для входу, налаштувань і безпеки. Аналітику та технічну телеметрію вмикаємо лише після вашої згоди. <a href="/cookie-policy.html">Докладніше</a></p>' +
        '</div>' +
        '<div class="ua-privacy-actions">' +
          '<button type="button" data-consent-action="reject">Лише необхідне</button>' +
          '<button type="button" data-consent-action="settings">Налаштувати</button>' +
          '<button type="button" class="ua-privacy-primary" data-consent-action="accept">Дозволити аналітику</button>' +
        '</div>' +
      '</div>';

    var dialog = document.createElement('dialog');
    dialog.id = 'ua-privacy-dialog';
    dialog.className = 'ua-privacy-dialog';
    dialog.setAttribute('aria-labelledby', 'ua-privacy-dialog-title');
    dialog.innerHTML =
      '<form method="dialog" class="ua-privacy-dialog__panel">' +
        '<div class="ua-privacy-dialog__heading">' +
          '<div>' +
            '<p class="ua-privacy-eyebrow">UA-Dim</p>' +
            '<h2 id="ua-privacy-dialog-title">Налаштування приватності</h2>' +
          '</div>' +
          '<button type="button" class="ua-privacy-close" data-consent-action="close" aria-label="Закрити налаштування приватності">×</button>' +
        '</div>' +
        '<div class="ua-privacy-option">' +
          '<div><strong>Необхідне сховище</strong><p>Вхід, обрані оголошення, фільтри, безпека та робота PWA.</p></div>' +
          '<span aria-label="Завжди увімкнено">Завжди</span>' +
        '</div>' +
        '<label class="ua-privacy-option" for="ua-consent-analytics">' +
          '<div><strong>Аналітика і діагностика</strong><p>GA4, web vitals і повідомлення про технічні помилки для покращення сервісу.</p></div>' +
          '<input id="ua-consent-analytics" type="checkbox" />' +
        '</label>' +
        '<p class="ua-privacy-links"><a href="/privacy.html">Політика конфіденційності</a> · <a href="/cookie-policy.html">Політика cookies</a></p>' +
        '<div class="ua-privacy-actions ua-privacy-actions--dialog">' +
          '<button type="button" data-consent-action="reject">Відхилити необов’язкове</button>' +
          '<button type="button" class="ua-privacy-primary" data-consent-action="save">Зберегти вибір</button>' +
        '</div>' +
      '</form>';

    document.body.appendChild(banner);
    document.body.appendChild(dialog);

    document.addEventListener('click', function (event) {
      var openTrigger = event.target.closest('[data-open-privacy-settings]');
      if (openTrigger) {
        event.preventDefault();
        openSettings(openTrigger);
        return;
      }
      var actionTrigger = event.target.closest('[data-consent-action]');
      if (!actionTrigger) return;
      var action = actionTrigger.getAttribute('data-consent-action');
      if (action === 'accept') setConsent(true, 'accept-all');
      if (action === 'reject') setConsent(false, 'necessary-only');
      if (action === 'settings') openSettings(actionTrigger);
      if (action === 'close') closeSettings();
      if (action === 'save') {
        var checkbox = document.getElementById('ua-consent-analytics');
        setConsent(Boolean(checkbox && checkbox.checked), 'preferences');
      }
    });

    dialog.addEventListener('close', function () {
      if (returnFocusTo && typeof returnFocusTo.focus === 'function') {
        returnFocusTo.focus();
      }
      returnFocusTo = null;
    });
    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) closeSettings();
    });

    renderBanner();
  }

  updateGoogleConsent();
  window.uaConsent = Object.freeze({
    allows: function (category) {
      return category === 'necessary' || (category === 'analytics' && analyticsAllowed());
    },
    getState: function () {
      return Object.assign({}, currentState);
    },
    openSettings: openSettings
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildInterface, { once: true });
  } else {
    buildInterface();
  }
})();
