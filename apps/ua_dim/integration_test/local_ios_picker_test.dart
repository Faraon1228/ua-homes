import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:ua_dim/screens/ua_dim_screen.dart';
import 'package:ua_dim/webview/navigation_policy.dart';
import 'package:webview_flutter/webview_flutter.dart';

// Needs `python3 apps/ua_dim/tool/local_auth_server.py` on 127.0.0.1:5050 and a disposable iOS
// simulator. The real WKWebView and the local mock upload page are real; the native iOS
// `com.uadim.app/native` channel (PHPicker) is MOCKED, so this is NOT a real OS picker test.
const _origin = 'http://127.0.0.1:5050';
const _channel = MethodChannel('com.uadim.app/native');

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

Future<List<Map>> _uploads() async =>
    ((await _server('/__uploads')) as List).cast<Map>();

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

Future<WebViewController> _mountPicker(WidgetTester tester) async {
  await tester.pumpWidget(
    MaterialApp(
      home: UaDimScreen(
        key: UniqueKey(),
        startUrl: Uri.parse('$_origin/__picker'),
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
  final controller = WebViewController.fromPlatform(
    webView.platform.params.controller,
  );
  await _until(
    () => _js(
      controller,
      "!!window.__uaDimPhotoPickerInstalled && !!document.getElementById('f')",
    ),
    'photo bridge installed on the picker page',
  );
  return controller;
}

Future<void> _clickInput(WebViewController controller) =>
    controller.runJavaScript("document.getElementById('f').click();");

Uint8List _photo(int length, int seed) =>
    Uint8List.fromList(List<int>.generate(length, (i) => (i + seed) % 256));

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  final calls = <String>[];
  late Future<Object?> Function(MethodCall call) pickHandler;

  setUp(() async {
    calls.clear();
    await _server('/__reset');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_channel, (call) async {
          calls.add(call.method);
          switch (call.method) {
            case 'supportsPhotoPicker':
              return true;
            case 'resetPhotoPicker':
              return null;
            default:
              return pickHandler(call);
          }
        });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_channel, null);
  });

  testWidgets('mocked picker: two photos reach the upload endpoint once', (
    tester,
  ) async {
    final photos = [_photo(200, 1), _photo(321, 7)];
    var next = 0;
    pickHandler = (call) async {
      if (call.method == 'pickPhotos') return photos.length;
      return {
        'name': 'p${next + 1}.jpg',
        'type': 'image/jpeg',
        'data': photos[next++],
      };
    };
    final controller = await _mountPicker(tester);
    await _clickInput(controller);
    await _until(() async => (await _uploads()).length >= 2, 'two uploads');
    await Future<void>.delayed(const Duration(seconds: 2));
    final uploads = await _uploads();
    expect(uploads.map((u) => u['name']), ['p1.jpg', 'p2.jpg']);
    expect(uploads.map((u) => u['size']), [200, 321]);
    expect(calls.where((c) => c == 'pickPhotos'), hasLength(1));
    expect(calls.last, 'resetPhotoPicker');
  });

  testWidgets('mocked picker: cancel uploads nothing and cleans up', (
    tester,
  ) async {
    pickHandler = (call) async => call.method == 'pickPhotos' ? 0 : null;
    final controller = await _mountPicker(tester);
    await _clickInput(controller);
    await _until(
      () async => calls.contains('resetPhotoPicker'),
      'cleanup after cancel',
    );
    await Future<void>.delayed(const Duration(seconds: 1));
    expect(await _uploads(), isEmpty);
    expect(calls, isNot(contains('readNextPhoto')));
  });

  testWidgets('mocked picker: denied access shows an error, then recovers', (
    tester,
  ) async {
    var deny = true;
    pickHandler = (call) async {
      if (call.method == 'pickPhotos') {
        if (deny) {
          throw PlatformException(
            code: 'denied',
            message: 'Немає доступу до фото',
          );
        }
        return 1;
      }
      return {'name': 'ok.jpg', 'type': 'image/jpeg', 'data': _photo(64, 3)};
    };
    final controller = await _mountPicker(tester);
    await _clickInput(controller);
    await _until(() async {
      await tester.pump(const Duration(milliseconds: 200));
      return find.text('Немає доступу до фото').evaluate().isNotEmpty;
    }, 'denied snackbar');
    expect(await _uploads(), isEmpty);

    deny = false;
    await _until(
      () async => calls.where((c) => c == 'resetPhotoPicker').isNotEmpty,
      'cleanup after denial',
    );
    await _clickInput(controller);
    await _until(
      () async => (await _uploads()).length == 1,
      'recovered upload',
    );
    expect((await _uploads()).single['name'], 'ok.jpg');
  });

  testWidgets('mocked picker: a second tap while picking does not re-open it', (
    tester,
  ) async {
    final gate = Completer<int>();
    pickHandler = (call) async {
      if (call.method == 'pickPhotos') return gate.future;
      return {'name': 'one.jpg', 'type': 'image/jpeg', 'data': _photo(90, 5)};
    };
    final controller = await _mountPicker(tester);
    await _clickInput(controller);
    await _until(
      () async => calls.contains('pickPhotos'),
      'first pick started',
    );
    await _clickInput(controller);
    await _until(() async {
      await tester.pump(const Duration(milliseconds: 200));
      return find
          .text('Зачекайте, попередні фото ще додаються.')
          .evaluate()
          .isNotEmpty;
    }, 'busy snackbar');
    expect(calls.where((c) => c == 'pickPhotos'), hasLength(1));
    gate.complete(1);
    await _until(() async => (await _uploads()).length == 1, 'single upload');
    await Future<void>.delayed(const Duration(seconds: 1));
    expect(await _uploads(), hasLength(1));
  });
}
