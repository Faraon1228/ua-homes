import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:ua_dim/screens/ua_dim_screen.dart';
import 'package:ua_dim/webview/auth_bridge.dart';
import 'package:ua_dim/webview/navigation_policy.dart';
import 'package:webview_flutter/webview_flutter.dart';

// Needs `python3 apps/ua_dim/tool/local_auth_server.py` on 127.0.0.1:5050 and a disposable
// simulator: the tests write synthetic tokens to the app's secure storage (keychain).
// Remounting UaDimScreen is an in-process remount, NOT an OS process restart.
const _origin = 'http://127.0.0.1:5050';
const _tokenA = 'synthetic-token-A';
const _tokenB = 'synthetic-token-B';
const _storage = FlutterSecureStorage();

Future<Object?> _server(String path) async {
  final client = HttpClient();
  try {
    final request = await client.getUrl(Uri.parse('$_origin$path'));
    final response = await request.close();
    return jsonDecode(await response.transform(utf8.decoder).join());
  } finally {
    client.close();
  }
}

Future<List<String>> _meTokens() async => ((await _server('/__log')) as List)
    .map((entry) => (entry as Map)['token'] as String)
    .toList();

Future<void> _until(
  Future<bool> Function() condition,
  String reason, {
  int seconds = 60,
}) async {
  final deadline = DateTime.now().add(Duration(seconds: seconds));
  while (DateTime.now().isBefore(deadline)) {
    if (await condition()) return;
    await Future<void>.delayed(const Duration(milliseconds: 300));
  }
  throw TestFailure('Timed out: $reason');
}

Future<bool> _js(WebViewController controller, String expression) async {
  try {
    return isJavaScriptTrue(
      await controller.runJavaScriptReturningResult(expression),
    );
  } catch (_) {
    return false;
  }
}

Future<WebViewController> _mount(
  WidgetTester tester, {
  String path = '/app',
}) async {
  await tester.pumpWidget(
    MaterialApp(
      home: UaDimScreen(
        key: UniqueKey(),
        startUrl: Uri.parse('$_origin$path'),
        navigationPolicy: const UaDimNavigationPolicy(
          allowedHosts: {'127.0.0.1'},
        ),
      ),
    ),
  );
  await tester.pump();
  await _until(
    () async => find.byType(WebViewWidget).evaluate().isNotEmpty,
    'WebViewWidget mounted',
  );
  final webView = tester.widget<WebViewWidget>(find.byType(WebViewWidget));
  return WebViewController.fromPlatform(webView.platform.params.controller);
}

// A disposed screen's WKWebView can outlive it and keep posting to its old coordinator, which
// shares the keychain with the next screen. The app only ever has one screen, so the harness
// stops that page's poller before remounting.
Future<void> _unmount(WidgetTester tester, WebViewController controller) async {
  await controller.runJavaScript(uaDimStopAuthBridgeScript);
  await tester.pumpWidget(const SizedBox());
  await tester.pump();
}

Future<bool> _released(WebViewController controller) =>
    _js(controller, 'window.__uaDimAuthReady === true');

const _webToken =
    'window.sessionStorage.getItem("uaDim.authToken") || '
    'window.localStorage.getItem("uaDim.authToken") || ""';

// Leaves the WKWebView origin storage in a known state: empty, or only stale token A.
Future<void> _prepareWeb(WidgetTester tester, {required bool staleA}) async {
  await _storage.delete(key: uaDimAuthStorageKey);
  final controller = await _mount(tester);
  await _until(
    () => _js(
      controller,
      'location.origin === "$_origin" && document.readyState === "complete"',
    ),
    'seed page loaded from local origin',
  );
  await controller.runJavaScript('''
    (() => {
      localStorage.clear();
      sessionStorage.clear();
      ${staleA ? 'localStorage.setItem("uaDim.authToken", "$_tokenA");' : ''}
      return true;
    })()
  ''');
  await _unmount(tester, controller);
}

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.fullyLive;

  setUp(() async {
    await _server('/__reset');
  });

  tearDownAll(() async {
    await _storage.delete(key: uaDimAuthStorageKey);
  });

  for (final staleA in [false, true]) {
    testWidgets(
      'cold start: secure B + ${staleA ? 'stale web A' : 'empty web'} validates only B',
      (tester) async {
        await _prepareWeb(tester, staleA: staleA);
        await _server('/__reset');
        await _storage.write(key: uaDimAuthStorageKey, value: _tokenB);

        final controller = await _mount(tester);
        await _until(() => _released(controller), 'handshake released');
        await _until(
          () async => (await _meTokens()).contains(_tokenB),
          '/me with B',
        );
        await Future<void>.delayed(const Duration(seconds: 4));

        expect((await _meTokens()).toSet(), {_tokenB});
        expect(await _storage.read(key: uaDimAuthStorageKey), _tokenB);
        expect(await _js(controller, '($_webToken) === "$_tokenB"'), isTrue);
      },
    );
  }

  testWidgets('slow restore (>3s) never releases or validates early', (
    tester,
  ) async {
    await _prepareWeb(tester, staleA: true);
    await _server('/__reset');
    await _server('/__config?slowImageMs=4500');
    await _storage.write(key: uaDimAuthStorageKey, value: _tokenB);

    final controller = await _mount(tester);
    await Future<void>.delayed(const Duration(milliseconds: 3800));
    expect(
      await _js(controller, 'document.readyState !== "complete"'),
      isTrue,
      reason: 'page must still be loading, i.e. restore has not run yet',
    );
    expect(await _released(controller), isFalse);
    expect(await _meTokens(), isEmpty);

    await _until(
      () => _released(controller),
      'handshake released',
      seconds: 90,
    );
    await _until(
      () async => (await _meTokens()).contains(_tokenB),
      '/me with B',
      seconds: 90,
    );
    expect((await _meTokens()).toSet(), {_tokenB});
    expect(await _storage.read(key: uaDimAuthStorageKey), _tokenB);
  });

  testWidgets('release failure shows recovery, no /me, retry releases', (
    tester,
  ) async {
    await _prepareWeb(tester, staleA: false);
    await _server('/__reset');
    await _server('/__config?slowImageMs=4500');
    await _storage.write(key: uaDimAuthStorageKey, value: _tokenB);

    final controller = await _mount(tester);
    // Restore reloads the page once; in the reloaded document, before its load finishes, make
    // the poller install (a real release-boundary step) throw while the native channels stay.
    await _until(
      () => _js(
        controller,
        'sessionStorage.getItem("uaDim.authToken") === "$_tokenB" && '
        'document.readyState !== "complete"',
      ),
      'reloaded document loading',
      seconds: 90,
    );
    await controller.runJavaScript('''
      (() => {
        Object.defineProperty(window, "__uaDimAuthBridgeInstalled", {
          get: () => false,
          set: () => { throw new Error("injected install failure"); },
        });
        return true;
      })()
    ''');
    await _until(
      () async {
        await tester.pump(const Duration(milliseconds: 200));
        return find
            .text('Не вдалося відновити сесію. Спробуйте ще раз.')
            .evaluate()
            .isNotEmpty;
      },
      'session error UI',
      seconds: 90,
    );
    expect(await _released(controller), isFalse);
    expect(await _meTokens(), isEmpty);
    expect(await _storage.read(key: uaDimAuthStorageKey), _tokenB);

    await _server('/__config?slowImageMs=0');
    await tester.tap(find.text('Спробувати ще раз'));
    await _until(() => _released(controller), 'released after retry');
    await _until(
      () async => (await _meTokens()).contains(_tokenB),
      '/me with B after retry',
    );
    expect((await _meTokens()).toSet(), {_tokenB});
    expect(await _storage.read(key: uaDimAuthStorageKey), _tokenB);
  });

  testWidgets('web logout clears secure token before an immediate remount', (
    tester,
  ) async {
    await _prepareWeb(tester, staleA: false);
    await _server('/__reset');
    await _storage.write(key: uaDimAuthStorageKey, value: _tokenB);

    final controller = await _mount(tester, path: '/seller');
    await _until(() => _released(controller), 'handshake released');
    await _until(
      () async => (await _meTokens()).contains(_tokenB),
      '/me with B',
    );
    await _until(() async {
      return _js(controller, '''
        (() => {
          const b = document.getElementById("header-logout-cta");
          if (!b) return false;
          b.click();
          return true;
        })()
      ''');
    }, 'real web logout button clicked');
    // No waiting for the 1.5s poller: remount as soon as the web has cleared its token.
    await _until(
      () => _js(controller, '($_webToken) === ""'),
      'web cleared token',
    );
    await _unmount(tester, controller);

    await _server('/__reset');
    final second = await _mount(tester);
    await _until(() => _released(second), 'second mount released');
    await Future<void>.delayed(const Duration(seconds: 3));
    expect(await _storage.read(key: uaDimAuthStorageKey), isNull);
    expect(await _meTokens(), isEmpty);
    expect(await _js(second, '($_webToken) === ""'), isTrue);
  });
}
