import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sentry_flutter/sentry_flutter.dart';
import 'package:ua_dim/main.dart';
import 'package:ua_dim/monitoring/sentry_monitoring.dart';
import 'package:ua_dim/screens/ua_dim_screen.dart';
import 'package:ua_dim/webview/auth_bridge.dart';
import 'package:ua_dim/webview/navigation_policy.dart';

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
    const policy = UaDimNavigationPolicy();
    expect(policy.isInternal(Uri.parse(uaDimProductionUrl)), isTrue);
    expect(
      policy.isInternal(Uri.parse('https://www.ua-dim.com/contact')),
      isTrue,
    );
    expect(policy.isInternal(Uri.parse('mailto:feedback@ua-dim.com')), isFalse);
  });

  test('UA-Dim navigation policy uses exact production host boundaries', () {
    const policy = UaDimNavigationPolicy();
    for (final host in uaDimProductionHosts) {
      expect(policy.isInternal(Uri.https(host, '/app')), isTrue);
      expect(policy.isInternal(Uri.http(host, '/app')), isTrue);
    }
    for (final url in [
      'https://feedback.ua-dim.com/contact',
      'https://evilua-dim.com/app',
      'https://ua-dim.com.evil.test/app',
      'https://example.com/app',
      'ftp://ua-dim.com/app',
      'mailto:feedback@ua-dim.com',
    ]) {
      expect(policy.isInternal(Uri.parse(url)), isFalse, reason: url);
    }
  });

  test('UA-Dim validates native listing links', () {
    const policy = UaDimNavigationPolicy();
    expect(
      policy.isListing(Uri.parse('https://ua-dim.com/listing/42')),
      isTrue,
    );
    expect(
      policy.isListing(Uri.parse('https://ua-dim.com/agencies/example')),
      isFalse,
    );
    expect(
      policy.parseNativeListing('https://ua-dim.com/listing/42')?.path,
      '/listing/42',
    );
    expect(
      policy.parseNativeListing('uadim://listing/42')?.path,
      '/listing/42',
    );
    expect(
      policy.parseNativeListing('https://ua-dim.com/listing/not-a-number'),
      isNull,
    );
    expect(
      policy.parseNativeListing('https://ua-dim.com/listing/42/edit'),
      isNull,
    );
    expect(policy.parseNativeListing('https://example.com/listing/42'), isNull);
    expect(policy.parseNativeListing('mailto:feedback@ua-dim.com'), isNull);
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
      expect(
        UaDimAuthBridgeMessage.parse(
          '{"version":1,"type":"auth","token":" token-123 "}',
        ),
        isA<UaDimAuthChanged>().having(
          (message) => message.token,
          'token',
          'token-123',
        ),
      );
      expect(
        UaDimAuthBridgeMessage.parse(
          '"{\\"version\\":1,\\"type\\":\\"auth\\",\\"token\\":null}"',
        ),
        isA<UaDimAuthChanged>().having(
          (message) => message.token,
          'token',
          isNull,
        ),
      );
      expect(UaDimAuthBridgeMessage.parse('token-123'), isNull);
      expect(UaDimAuthBridgeMessage.parse('   '), isNull);
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

  test('UA-Dim auth lifecycle characterizes login and account switching', () {
    final login = planUaDimAuthTransition(
      previousToken: null,
      nextToken: ' login-token ',
    );
    expect(login.changed, isTrue);
    expect(login.nextToken, 'login-token');
    expect(login.shouldWriteStoredToken, isTrue);
    expect(login.shouldDeleteStoredToken, isFalse);

    final accountSwitch = planUaDimAuthTransition(
      previousToken: login.nextToken,
      nextToken: 'realtor-token',
    );
    expect(accountSwitch.previousToken, 'login-token');
    expect(accountSwitch.nextToken, 'realtor-token');
    expect(accountSwitch.changed, isTrue);
    expect(accountSwitch.shouldWriteStoredToken, isTrue);
  });

  test('UA-Dim auth lifecycle characterizes logout and duplicate messages', () {
    final logout = planUaDimAuthTransition(
      previousToken: 'token-123',
      nextToken: null,
    );
    expect(logout.changed, isTrue);
    expect(logout.shouldDeleteStoredToken, isTrue);
    expect(logout.shouldWriteStoredToken, isFalse);

    final duplicate = planUaDimAuthTransition(
      previousToken: ' token-123 ',
      nextToken: 'token-123',
    );
    expect(duplicate.changed, isFalse);
  });

  test('UA-Dim only accepts a 401 rejection for the active token', () {
    expect(
      shouldRejectUaDimAuthToken(
        currentToken: 'token-123',
        rejectedToken: ' token-123 ',
      ),
      isTrue,
    );
    expect(
      shouldRejectUaDimAuthToken(
        currentToken: 'new-token',
        rejectedToken: 'old-token',
      ),
      isFalse,
    );
    expect(
      shouldRejectUaDimAuthToken(
        currentToken: null,
        rejectedToken: 'old-token',
      ),
      isFalse,
    );
  });

  test('UA-Dim auth bridge rejects unrelated and malformed contracts', () {
    expect(
      UaDimAuthBridgeMessage.parse(
        '{"version":1,"type":"logout","token":"token-123"}',
      ),
      isNull,
    );
    expect(
      UaDimAuthBridgeMessage.parse('{"type":"auth","token":"token-123"}'),
      isNull,
    );
    expect(
      UaDimAuthBridgeMessage.parse(
        '{"version":2,"type":"auth","token":"token-123"}',
      ),
      isNull,
    );
    expect(UaDimAuthBridgeMessage.parse('{"version":1,"type":"auth"}'), isNull);
    expect(
      UaDimAuthBridgeMessage.parse('{"version":1,"type":"auth","token":123}'),
      isNull,
    );
    expect(UaDimAuthBridgeMessage.parse('{"version":1,"type":"auth"'), isNull);
    expect(UaDimAuthBridgeMessage.parse('["token-123"]'), isNull);
  });

  test(
    'UA-Dim auth coordinator delegates the complete token lifecycle',
    () async {
      final store = _RecordingAuthStore();
      final consumer = _RecordingAuthConsumer();
      final coordinator = UaDimAuthCoordinator(store, consumer);

      expect(
        await coordinator.handle(
          '{"version":1,"type":"auth","token":"login-token"}',
        ),
        isTrue,
      );
      expect(
        await coordinator.handle(
          '{"version":1,"type":"auth","token":"login-token"}',
        ),
        isFalse,
      );
      expect(
        await coordinator.handle(
          '{"version":1,"type":"auth","token":"account-token"}',
        ),
        isTrue,
      );
      expect(
        await coordinator.handle('{"version":1,"type":"auth","token":null}'),
        isTrue,
      );
      expect(store.operations, [
        'write:login-token',
        'write:account-token',
        'delete',
      ]);
      expect(consumer.tokens, ['login-token', 'account-token', null]);
    },
  );

  test(
    'UA-Dim auth coordinator ignores unrelated and stale rejections',
    () async {
      final store = _RecordingAuthStore();
      final consumer = _RecordingAuthConsumer();
      final coordinator = UaDimAuthCoordinator(
        store,
        consumer,
        initialToken: 'active-token',
      );

      expect(await coordinator.handle('{"type":"tracking"}'), isFalse);
      expect(await coordinator.reject('stale-token'), isFalse);
      expect(await coordinator.reject('active-token'), isTrue);
      expect(store.operations, ['delete']);
      expect(consumer.tokens, [null]);
    },
  );

  test('UA-Dim auth coordinator serializes overlapping messages', () async {
    final store = _RecordingAuthStore(delay: const Duration(milliseconds: 5));
    final consumer = _RecordingAuthConsumer();
    final coordinator = UaDimAuthCoordinator(store, consumer);

    await Future.wait([
      coordinator.handle('{"version":1,"type":"auth","token":"login-token"}'),
      coordinator.handle('{"version":1,"type":"auth","token":"account-token"}'),
      coordinator.handle('{"version":1,"type":"auth","token":null}'),
    ]);

    expect(coordinator.currentToken, isNull);
    expect(store.operations, [
      'write:login-token',
      'write:account-token',
      'delete',
    ]);
    expect(consumer.tokens, ['login-token', 'account-token', null]);
  });

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

class _RecordingAuthStore implements UaDimAuthTokenStore {
  _RecordingAuthStore({this.delay = Duration.zero});

  final Duration delay;
  final List<String> operations = [];

  @override
  Future<void> delete() async {
    await Future<void>.delayed(delay);
    operations.add('delete');
  }

  @override
  Future<void> write(String token) async {
    await Future<void>.delayed(delay);
    operations.add('write:$token');
  }
}

class _RecordingAuthConsumer implements UaDimAuthTokenConsumer {
  final List<String?> tokens = [];

  @override
  Future<void> setAuthToken(String? token) async => tokens.add(token);
}

// Monitoring configuration is tested without initializing a transport or using a
// real DSN, keeping verification safe and deterministic.
