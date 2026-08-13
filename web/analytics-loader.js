(function () {
  'use strict';

  var loaded = false;

  function analyticsAllowed() {
    return Boolean(window.uaConsent && window.uaConsent.allows('analytics'));
  }

  function loadAnalytics(discardPreConsentEvents) {
    if (loaded || !analyticsAllowed()) return;
    loaded = true;
    if (discardPreConsentEvents) {
      window.dataLayer = [];
      window.__UA_ANALYTICS_PENDING_EVENTS__ = [];
    } else {
      window.dataLayer = window.dataLayer || [];
    }
    var script = document.createElement('script');
    script.src = '/analytics.js?v=ua-consent-01';
    script.async = true;
    document.body.appendChild(script);
  }

  function loadOnIntent() {
    window.__UA_ANALYTICS_INTENT__ = true;
    loadAnalytics(false);
  }

  window.addEventListener('ua:consent-change', function (event) {
    if (!event.detail || !event.detail.analytics) return;
    loadAnalytics(event.detail.previousAnalytics === false);
  });
  window.addEventListener('uah:meaningful-interaction', loadOnIntent, { once: true });
  ['pointerdown', 'keydown', 'touchstart'].forEach(function (name) {
    window.addEventListener(name, loadOnIntent, { once: true, capture: true, passive: true });
  });
  window.addEventListener('load', function () {
    var scheduledLoad = function () {
      loadAnalytics(false);
    };
    if ('requestIdleCallback' in window) {
      requestIdleCallback(scheduledLoad, { timeout: 2000 });
    } else {
      setTimeout(scheduledLoad, 0);
    }
  }, { once: true });
})();
