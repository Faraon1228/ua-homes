// ignore_for_file: experimental_member_use

import 'package:flutter/widgets.dart';
import 'package:sentry_flutter/sentry_flutter.dart';

const _filtered = '[Filtered]';
final _privateValue = RegExp(
  r'(?:bearer\s+[\w.-]+|[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?:\+?\d[\d ()-]{8,}\d)|(?:password|token|secret|authorization)=?[^\s&]*)',
  caseSensitive: false,
);
final _expectedFailure = RegExp(
  r'(?:aborterror|socketexception|clientexception|failed host lookup|connection reset|network is unreachable|timed out|offline|unauthorized|forbidden|validation|rate.?limit|too many requests|status(?:code)?\s*[:=]?\s*4\d\d)',
  caseSensitive: false,
);

class UaDimSentryConfig {
  const UaDimSentryConfig({
    required this.dsn,
    required this.environment,
    required this.release,
    required this.tracesSampleRate,
    required this.profilesSampleRate,
  });

  factory UaDimSentryConfig.fromEnvironment() => UaDimSentryConfig(
    dsn: const String.fromEnvironment('UA_DIM_SENTRY_DSN'),
    environment: const String.fromEnvironment(
      'UA_DIM_SENTRY_ENVIRONMENT',
      defaultValue: 'production',
    ),
    release: const String.fromEnvironment('UA_DIM_SENTRY_RELEASE'),
    tracesSampleRate: parseSentrySampleRate(
      const String.fromEnvironment(
        'UA_DIM_SENTRY_TRACES_SAMPLE_RATE',
        defaultValue: '0.01',
      ),
      0.01,
    ),
    profilesSampleRate: parseSentrySampleRate(
      const String.fromEnvironment(
        'UA_DIM_SENTRY_PROFILES_SAMPLE_RATE',
        defaultValue: '0',
      ),
      0,
    ),
  );

  final String dsn;
  final String environment;
  final String release;
  final double tracesSampleRate;
  final double profilesSampleRate;

  bool get enabled => dsn.trim().isNotEmpty;
}

double parseSentrySampleRate(String value, double fallback) {
  final parsed = double.tryParse(value);
  return parsed != null && parsed >= 0 && parsed <= 1 ? parsed : fallback;
}

String sanitizeSentryText(String value) =>
    _privateValue.hasMatch(value) ? _filtered : value;

bool isExpectedSentryFailure(Object? value) =>
    _expectedFailure.hasMatch(value?.toString() ?? '');

bool _isExpectedSentryEvent(SentryEvent event) {
  if (isExpectedSentryFailure(event.throwable) ||
      isExpectedSentryFailure(event.message?.formatted)) {
    return true;
  }
  return event.exceptions?.any(
        (exception) =>
            isExpectedSentryFailure(exception.type) ||
            isExpectedSentryFailure(exception.value),
      ) ??
      false;
}

Breadcrumb? filterSentryBreadcrumb(Breadcrumb? breadcrumb, Hint _) {
  if (breadcrumb == null) return null;
  final category = (breadcrumb.category ?? '').toLowerCase();
  if (RegExp(
    r'(?:http|navigation|console|webview|auth|upload|input)',
  ).hasMatch(category)) {
    return null;
  }
  breadcrumb.message = breadcrumb.message == null
      ? null
      : sanitizeSentryText(breadcrumb.message!);
  breadcrumb.data = null;
  return breadcrumb;
}

SentryEvent? filterSentryEvent(SentryEvent event, Hint hint) {
  if (_isExpectedSentryEvent(event)) {
    return null;
  }

  event.user = null;
  event.request = null;
  // ignore: deprecated_member_use
  event.extra?.clear();
  event.breadcrumbs = event.breadcrumbs
      ?.map((breadcrumb) => filterSentryBreadcrumb(breadcrumb, Hint()))
      .whereType<Breadcrumb>()
      .toList(growable: false);
  if (event.message != null) {
    event.message!.formatted = sanitizeSentryText(event.message!.formatted);
    event.message!.template = null;
    event.message!.params = null;
  }
  for (final exception in event.exceptions ?? const <SentryException>[]) {
    if (exception.value != null) {
      exception.value = sanitizeSentryText(exception.value!);
    }
  }
  return event;
}

Future<void> runUaDimApp(Widget app, {UaDimSentryConfig? config}) async {
  final resolved = config ?? UaDimSentryConfig.fromEnvironment();
  if (!resolved.enabled) {
    runApp(app);
    return;
  }

  await SentryFlutter.init((options) {
    options
      ..dsn = resolved.dsn
      ..environment = resolved.environment
      ..release = resolved.release.trim().isEmpty ? null : resolved.release
      ..sendDefaultPii = false
      ..tracesSampleRate = resolved.tracesSampleRate
      ..profilesSampleRate = resolved.profilesSampleRate
      ..enableAutoPerformanceTracing = resolved.tracesSampleRate > 0
      ..enableAutoNativeBreadcrumbs = false
      ..enableAppLifecycleBreadcrumbs = true
      ..maxBreadcrumbs = 30
      ..beforeSend = filterSentryEvent
      ..beforeBreadcrumb = filterSentryBreadcrumb;
  }, appRunner: () => runApp(SentryWidget(child: app)));
}
