import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sentry_flutter/sentry_flutter.dart';
import 'package:ua_dim/main.dart';
import 'package:ua_dim/monitoring/sentry_monitoring.dart';
import 'package:ua_dim/screens/ua_dim_screen.dart';

void main() {
  testWidgets('UA-Dim app has its own identity', (tester) async {
    await tester.pumpWidget(
      const UaDimApp(home: Scaffold(body: Text('UA-Dim mobile shell'))),
    );

    final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(app.title, 'UA-Dim');
    expect(find.text('UA-Dim mobile shell'), findsOneWidget);
    expect(uaDimProductionUrl, contains('ua-dim.com'));
    expect(uaDimProductionUrl, isNot(contains('demo')));
    expect(uaDimProductionUrl, contains('source=ua-dim-app'));
    expect(uaDimProductionUrl, contains('release=20260820-photo-library'));
    expect(isUaDimInternalUri(Uri.parse(uaDimProductionUrl)), isTrue);
    expect(
      isUaDimInternalUri(Uri.parse('https://feedback.ua-dim.com/contact')),
      isTrue,
    );
    expect(
      isUaDimInternalUri(Uri.parse('mailto:feedback@ua-dim.com')),
      isFalse,
    );
  });

  test('UA-Dim validates native listing links', () {
    expect(
      isUaDimListingUri(Uri.parse('https://ua-dim.com/listing/42')),
      isTrue,
    );
    expect(
      isUaDimListingUri(Uri.parse('https://ua-dim.com/agencies/example')),
      isFalse,
    );
    expect(
      parseUaDimNativeUri('https://ua-dim.com/listing/42')?.path,
      '/listing/42',
    );
    expect(parseUaDimNativeUri('uadim://listing/42')?.path, '/listing/42');
    expect(
      parseUaDimNativeUri('https://ua-dim.com/listing/not-a-number'),
      isNull,
    );
    expect(parseUaDimNativeUri('https://ua-dim.com/listing/42/edit'), isNull);
    expect(parseUaDimNativeUri('https://example.com/listing/42'), isNull);
    expect(parseUaDimNativeUri('mailto:feedback@ua-dim.com'), isNull);
  });

  test('UA-Dim normalizes JavaScript boolean results', () {
    expect(isJavaScriptTrue(true), isTrue);
    expect(isJavaScriptTrue('true'), isTrue);
    expect(isJavaScriptTrue(1), isTrue);
    expect(isJavaScriptTrue(false), isFalse);
    expect(isJavaScriptTrue('false'), isFalse);
    expect(isJavaScriptTrue(null), isFalse);
  });

  test(
    'UA-Dim parses auth bridge payloads without relying on empty messages',
    () {
      expect(parseUaDimAuthBridgeToken('token-123'), 'token-123');
      expect(
        parseUaDimAuthBridgeToken('{"type":"auth","token":" token-123 "}'),
        'token-123',
      );
      expect(parseUaDimAuthBridgeToken('{"type":"auth","token":null}'), isNull);
      expect(
        parseUaDimAuthBridgeToken(
          '"{\\"type\\":\\"auth\\",\\"token\\":\\" token-123 \\"}"',
        ),
        'token-123',
      );
      expect(parseUaDimAuthBridgeToken('   '), isNull);
    },
  );

  test(
    'UA-Dim auth restore avoids reload once local bootstrap token is valid',
    () {
      final plan = planUaDimAuthRestore(
        storedToken: 'token-123',
        sessionToken: null,
        localToken: 'token-123',
        hasCurrentUser: true,
      );
      expect(plan.shouldReload, isFalse);
      expect(plan.sessionToken, 'token-123');
      expect(plan.localToken, 'token-123');
      expect(plan.clearCurrentUser, isFalse);
    },
  );

  test(
    'UA-Dim auth restore reloads when only session storage has the token',
    () {
      final plan = planUaDimAuthRestore(
        storedToken: 'token-123',
        sessionToken: 'token-123',
        localToken: null,
        hasCurrentUser: true,
      );
      expect(plan.shouldReload, isTrue);
      expect(plan.sessionToken, 'token-123');
      expect(plan.localToken, 'token-123');
      expect(plan.clearCurrentUser, isFalse);
    },
  );

  test(
    'UA-Dim auth restore clears stale browser auth state when native token is absent',
    () {
      final plan = planUaDimAuthRestore(
        storedToken: null,
        sessionToken: 'stale-token',
        localToken: null,
        hasCurrentUser: true,
      );
      expect(plan.shouldReload, isTrue);
      expect(plan.sessionToken, isNull);
      expect(plan.localToken, isNull);
      expect(plan.clearCurrentUser, isTrue);
    },
  );

  test('Sentry configuration is disabled without a DSN', () {
    const config = UaDimSentryConfig(
      dsn: '',
      environment: 'test',
      release: 'test-release',
      tracesSampleRate: 0.01,
      profilesSampleRate: 0,
    );
    expect(config.enabled, isFalse);
    expect(parseSentrySampleRate('invalid', 0.01), 0.01);
    expect(parseSentrySampleRate('2', 0.01), 0.01);
  });

  test('Sentry enabled configuration and privacy filters are conservative', () {
    const config = UaDimSentryConfig(
      dsn: 'https://public@example.ingest.sentry.io/1',
      environment: 'test',
      release: 'test-release',
      tracesSampleRate: 0.01,
      profilesSampleRate: 0,
    );
    expect(config.enabled, isTrue);
    expect(config.tracesSampleRate, 0.01);
    expect(config.profilesSampleRate, 0);
    expect(sanitizeSentryText('private@example.test'), '[Filtered]');
    expect(
      isExpectedSentryFailure(Exception('SocketException: offline')),
      isTrue,
    );
    expect(
      filterSentryBreadcrumb(
        Breadcrumb.http(
          url: Uri.parse('https://ua-dim.com/listing/1?token=x'),
          method: 'GET',
        ),
        Hint(),
      ),
      isNull,
    );
    final safe = filterSentryBreadcrumb(
      Breadcrumb(category: 'app.lifecycle', message: 'resumed'),
      Hint(),
    );
    expect(safe?.message, 'resumed');
    expect(safe?.data, isNull);
  });

  test('Sentry expected-error filtering only inspects error diagnostics', () {
    final crash = SentryEvent(
      throwable: StateError('Null check operator used on a null value'),
      exceptions: [
        SentryException(
          type: 'StateError',
          value: 'Null check operator used on a null value',
        ),
      ],
      breadcrumbs: [
        Breadcrumb(
          category: 'app.lifecycle',
          message: 'validation completed before crash',
        ),
      ],
    );
    final retained = filterSentryEvent(crash, Hint());
    expect(retained, same(crash));
    expect(retained?.breadcrumbs?.single.message, contains('validation'));

    expect(
      filterSentryEvent(
        SentryEvent(
          exceptions: [
            SentryException(
              type: 'ValidationError',
              value: 'Listing validation failed',
            ),
          ],
        ),
        Hint(),
      ),
      isNull,
    );
    expect(
      filterSentryEvent(
        SentryEvent(throwable: Exception('Unauthorized request')),
        Hint(),
      ),
      isNull,
    );
  });
}

// Monitoring configuration is tested without initializing a transport or using a
// real DSN, keeping verification safe and deterministic.
