import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

const String _apiKey = String.fromEnvironment('UA_DIM_FIREBASE_API_KEY');
const String _appId = String.fromEnvironment('UA_DIM_FIREBASE_APP_ID');
const String _messagingSenderId = String.fromEnvironment(
  'UA_DIM_FIREBASE_MESSAGING_SENDER_ID',
);
const String _projectId = String.fromEnvironment('UA_DIM_FIREBASE_PROJECT_ID');
const String _pushApiUrl = 'https://ua-dim.com/api/push/devices';

bool get hasFirebaseConfiguration =>
    _apiKey.isNotEmpty &&
    _appId.isNotEmpty &&
    _messagingSenderId.isNotEmpty &&
    _projectId.isNotEmpty;

class MobilePushService {
  MobilePushService._();

  static final instance = MobilePushService._();

  StreamSubscription<String>? _tokenSubscription;
  StreamSubscription<RemoteMessage>? _messageOpenSubscription;
  String? _authToken;
  String? _deviceToken;
  void Function(Uri uri)? _onOpenUri;
  bool _initialized = false;
  Future<void> _authTransition = Future<void>.value();

  Future<void> initialize({required void Function(Uri uri) onOpenUri}) async {
    _onOpenUri = onOpenUri;
    if (_initialized || kIsWeb || !hasFirebaseConfiguration) return;
    _initialized = true;

    try {
      await Firebase.initializeApp(
        options: const FirebaseOptions(
          apiKey: _apiKey,
          appId: _appId,
          messagingSenderId: _messagingSenderId,
          projectId: _projectId,
        ),
      );
      final messaging = FirebaseMessaging.instance;
      await messaging.requestPermission(alert: true, badge: true, sound: true);
      _tokenSubscription = messaging.onTokenRefresh.listen((token) {
        _deviceToken = token;
        unawaited(_registerCurrentDevice());
      });
      _messageOpenSubscription = FirebaseMessaging.onMessageOpenedApp.listen(
        _openMessage,
      );
      final initialMessage = await messaging.getInitialMessage();
      if (initialMessage != null) _openMessage(initialMessage);
      if (Platform.isIOS && !await _waitForApnsToken(messaging)) {
        debugPrint('UA-Dim APNs token is not available yet');
        return;
      }
      try {
        _deviceToken = await messaging.getToken();
      } on FirebaseException catch (error) {
        debugPrint('UA-Dim FCM token unavailable: ${error.code}');
      }
    } on FirebaseException catch (error) {
      _initialized = false;
      debugPrint('UA-Dim Firebase initialization failed: ${error.code}');
    }
  }

  Future<void> setAuthToken(String? token) {
    final transition = _authTransition.then((_) => _applyAuthToken(token));
    _authTransition = transition;
    return transition;
  }

  Future<void> _applyAuthToken(String? token) async {
    final nextToken = token?.trim().isNotEmpty == true ? token!.trim() : null;
    final previousToken = _authToken;
    if (previousToken != null && previousToken != nextToken) {
      await _unregisterCurrentDevice(previousToken);
    }
    _authToken = nextToken;
    await _registerCurrentDevice();
  }

  Future<bool> _waitForApnsToken(FirebaseMessaging messaging) async {
    for (var attempt = 0; attempt < 20; attempt += 1) {
      if (await messaging.getAPNSToken() != null) return true;
      await Future<void>.delayed(const Duration(milliseconds: 250));
    }
    return false;
  }

  void _openMessage(RemoteMessage message) {
    final uri = Uri.tryParse(message.data['url']?.toString() ?? '');
    if (uri != null) _onOpenUri?.call(uri);
  }

  Future<void> _registerCurrentDevice() async {
    final authToken = _authToken;
    final deviceToken = _deviceToken;
    if (authToken == null || deviceToken == null || kIsWeb) return;
    try {
      final response = await http.post(
        Uri.parse(_pushApiUrl),
        headers: {
          HttpHeaders.authorizationHeader: 'Bearer $authToken',
          HttpHeaders.contentTypeHeader: 'application/json',
        },
        body: jsonEncode({
          'token': deviceToken,
          'platform': Platform.isIOS ? 'ios' : 'android',
        }),
      );
      if (response.statusCode < 200 || response.statusCode >= 300) {
        debugPrint(
          'UA-Dim push registration failed with HTTP ${response.statusCode}',
        );
      }
    } on http.ClientException catch (error) {
      debugPrint('UA-Dim push registration unavailable: $error');
    } on SocketException catch (error) {
      debugPrint('UA-Dim push registration unavailable: $error');
    }
  }

  Future<void> _unregisterCurrentDevice(String authToken) async {
    final deviceToken = _deviceToken;
    if (deviceToken == null || kIsWeb) return;
    try {
      final response = await http.delete(
        Uri.parse(_pushApiUrl),
        headers: {
          HttpHeaders.authorizationHeader: 'Bearer $authToken',
          HttpHeaders.contentTypeHeader: 'application/json',
        },
        body: jsonEncode({'token': deviceToken}),
      );
      if (response.statusCode < 200 || response.statusCode >= 300) {
        debugPrint(
          'UA-Dim push unregistration failed with HTTP ${response.statusCode}',
        );
      }
    } on http.ClientException catch (error) {
      debugPrint('UA-Dim push unregistration unavailable: $error');
    } on SocketException catch (error) {
      debugPrint('UA-Dim push unregistration unavailable: $error');
    }
  }

  Future<void> dispose() async {
    await _tokenSubscription?.cancel();
    await _messageOpenSubscription?.cancel();
  }
}
