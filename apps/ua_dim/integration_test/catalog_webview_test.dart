import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:ua_dim/main.dart' as app;
import 'package:ua_dim/screens/ua_dim_screen.dart';
import 'package:webview_flutter/webview_flutter.dart';

Future<void> waitForPage(
  WebViewController controller,
  String expression,
) async {
  final deadline = DateTime.now().add(const Duration(seconds: 60));
  while (DateTime.now().isBefore(deadline)) {
    final result = await controller.runJavaScriptReturningResult(expression);
    if (isJavaScriptTrue(result)) return;
    await Future<void>.delayed(const Duration(milliseconds: 500));
  }
  throw TestFailure('WebView timed out waiting for: $expression');
}

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.fullyLive;

  testWidgets('production catalog works inside the native WebView', (
    tester,
  ) async {
    await app.main();
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.byType(WebViewWidget), findsOneWidget);
    final webView = tester.widget<WebViewWidget>(find.byType(WebViewWidget));
    final controller = WebViewController.fromPlatform(
      webView.platform.params.controller,
    );

    await tester.runAsync(() async {
      await waitForPage(
        controller,
        'innerWidth > 0 && !!document.querySelector("#hero-offer-toggle a")',
      );
      final initialLayout = await controller.runJavaScriptReturningResult('''
        JSON.stringify({
          width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
          seller: document.querySelector("#hero-offer-toggle a").getAttribute("href"),
          url: location.href
        })
      ''');
      // ignore: avoid_print
      print('Initial native layout: $initialLayout');
      expect(
        isJavaScriptTrue(
          await controller.runJavaScriptReturningResult(
            'document.documentElement.scrollWidth <= innerWidth',
          ),
        ),
        isTrue,
        reason: 'Native catalog must not overflow horizontally',
      );
      expect(
        isJavaScriptTrue(
          await controller.runJavaScriptReturningResult(
            'document.querySelector("#hero-offer-toggle a").getAttribute("href") === "/seller"',
          ),
        ),
        isTrue,
        reason: 'Sell must navigate to the internal seller cabinet',
      );
      await controller.runJavaScript('''
        localStorage.setItem("uaDim.privacyConsent.v1", JSON.stringify({
          version: 1, analytics: false, updatedAt: new Date().toISOString()
        }));
        document.querySelectorAll("#hero-offer-toggle button")[1].click();
      ''');
      await waitForPage(
        controller,
        'location.search.includes("listingType=rent") && '
        'document.querySelector("#hero-offer-toggle button:last-child")'
        '.getAttribute("aria-pressed") === "true"',
      );
      await controller.reload();
      await waitForPage(
        controller,
        '!!document.querySelector("#hero-offer-toggle button:last-child") && '
        'document.querySelector("#hero-offer-toggle button:last-child")'
        '.getAttribute("aria-pressed") === "true"',
      );
      await controller.runJavaScript(
        'document.querySelector("#hero-offer-toggle a").click()',
      );
      await waitForPage(
        controller,
        'location.pathname === "/seller" && '
        'document.documentElement.classList.contains("seller-page")',
      );
      await controller.loadRequest(Uri.parse(uaDimProductionUrl));
      await waitForPage(
        controller,
        '!!document.querySelector("#hero-offer-toggle a")',
      );
      final layout = await controller.runJavaScriptReturningResult('''
        JSON.stringify({
          viewport: innerWidth,
          overflow: document.documentElement.scrollWidth > innerWidth,
          actions: document.querySelector("#hero-offer-toggle").textContent.trim()
        })
      ''');
      // Keep the native viewport and loaded release in the test log.
      // ignore: avoid_print
      print('Native WebView layout: ${jsonEncode(layout)}');
    });
    await tester.pump();
    expect(tester.takeException(), isNull);
  });
}
