// Test-only entrypoint for real OS-process restart checks against the isolated local server
// (`python3 apps/ua_dim/tool/local_auth_server.py`). Run it only on a disposable simulator:
//   flutter run -d <sim> -t tool/local_restart_main.dart
// The server decides once per launch whether to seed synthetic token B ("seed"), arm the web
// logout click ("logout") or do nothing; it never re-seeds. Secure storage is reported to the
// server as a boolean only.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:ua_dim/screens/ua_dim_screen.dart';
import 'package:ua_dim/webview/auth_bridge.dart';
import 'package:ua_dim/webview/navigation_policy.dart';

const _origin = 'http://127.0.0.1:5050';
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

Future<void> _event(String kind, Object value) =>
    _server('/__restart/event?kind=$kind&v=$value');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final next = await _server('/__restart/next') as Map;
  final action = next['action'] as String;
  if (action == 'seed') {
    await _storage.write(key: uaDimAuthStorageKey, value: 'synthetic-token-B');
  }
  final present = await _storage.read(key: uaDimAuthStorageKey) != null;
  await _event('launch', '$action;secure=$present');
  runApp(
    MaterialApp(
      home: UaDimScreen(
        startUrl: Uri.parse('$_origin/seller'),
        navigationPolicy: const UaDimNavigationPolicy(
          allowedHosts: {'127.0.0.1'},
        ),
      ),
    ),
  );
}
