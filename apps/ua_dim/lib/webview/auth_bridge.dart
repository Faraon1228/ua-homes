import 'dart:async';
import 'dart:convert';

const String uaDimAuthStorageKey = 'uaDim.authToken';

String? normalizeUaDimAuthToken(String? token) {
  final trimmed = token?.trim();
  return trimmed == null || trimmed.isEmpty ? null : trimmed;
}

Object? decodeUaDimJsonEnvelope(String message) {
  Object? decoded = message.trim();
  for (var attempt = 0; attempt < 2 && decoded is String; attempt += 1) {
    final candidate = decoded.trim();
    if (candidate.isEmpty) return null;
    if (!candidate.startsWith('{') &&
        !candidate.startsWith('[') &&
        !candidate.startsWith('"')) {
      break;
    }
    try {
      decoded = jsonDecode(candidate);
    } on FormatException {
      return null;
    }
  }
  return decoded;
}

sealed class UaDimAuthBridgeMessage {
  const UaDimAuthBridgeMessage();

  static UaDimAuthBridgeMessage? parse(String message) {
    final decoded = decodeUaDimJsonEnvelope(message);
    if (decoded is! Map ||
        decoded['version'] != 1 ||
        decoded['type'] != 'auth' ||
        !decoded.containsKey('token')) {
      return null;
    }
    final token = decoded['token'];
    if (token != null && token is! String) return null;
    return UaDimAuthChanged(normalizeUaDimAuthToken(token as String?));
  }
}

final class UaDimAuthChanged extends UaDimAuthBridgeMessage {
  const UaDimAuthChanged(this.token);

  final String? token;
}

class UaDimAuthTransition {
  const UaDimAuthTransition({
    required this.previousToken,
    required this.nextToken,
  });

  final String? previousToken;
  final String? nextToken;

  bool get changed => previousToken != nextToken;
  bool get shouldDeleteStoredToken => changed && nextToken == null;
  bool get shouldWriteStoredToken => changed && nextToken != null;
}

UaDimAuthTransition planUaDimAuthTransition({
  required String? previousToken,
  required String? nextToken,
}) {
  return UaDimAuthTransition(
    previousToken: normalizeUaDimAuthToken(previousToken),
    nextToken: normalizeUaDimAuthToken(nextToken),
  );
}

bool shouldRejectUaDimAuthToken({
  required String? currentToken,
  required String rejectedToken,
}) =>
    normalizeUaDimAuthToken(currentToken) ==
    normalizeUaDimAuthToken(rejectedToken);

class UaDimAuthRestorePlan {
  const UaDimAuthRestorePlan({
    required this.shouldReload,
    required this.sessionToken,
    required this.localToken,
    required this.clearCurrentUser,
  });

  final bool shouldReload;
  final String? sessionToken;
  final String? localToken;
  final bool clearCurrentUser;
}

UaDimAuthRestorePlan planUaDimAuthRestore({
  required String? storedToken,
  required String? sessionToken,
  required String? localToken,
  required bool hasCurrentUser,
}) {
  final normalizedStoredToken = normalizeUaDimAuthToken(storedToken);
  final normalizedSessionToken = normalizeUaDimAuthToken(sessionToken);
  final normalizedLocalToken = normalizeUaDimAuthToken(localToken);

  if (normalizedStoredToken != null) {
    return UaDimAuthRestorePlan(
      shouldReload: normalizedLocalToken != normalizedStoredToken,
      sessionToken: normalizedStoredToken,
      localToken: normalizedStoredToken,
      clearCurrentUser: false,
    );
  }

  final hasStaleAuthState =
      normalizedSessionToken != null ||
      normalizedLocalToken != null ||
      hasCurrentUser;
  return UaDimAuthRestorePlan(
    shouldReload: hasStaleAuthState,
    sessionToken: null,
    localToken: null,
    clearCurrentUser: hasCurrentUser,
  );
}

abstract interface class UaDimAuthTokenStore {
  Future<void> write(String token);
  Future<void> delete();
}

abstract interface class UaDimAuthTokenConsumer {
  Future<void> setAuthToken(String? token);
}

class UaDimAuthCoordinator {
  UaDimAuthCoordinator(this._store, this._consumer, {String? initialToken})
    : _currentToken = normalizeUaDimAuthToken(initialToken);

  final UaDimAuthTokenStore _store;
  final UaDimAuthTokenConsumer _consumer;
  String? _currentToken;
  Future<void> _operation = Future<void>.value();

  String? get currentToken => _currentToken;

  Future<bool> handle(String message) => _serialize(() async {
    final parsed = UaDimAuthBridgeMessage.parse(message);
    if (parsed is! UaDimAuthChanged) return false;
    final transition = planUaDimAuthTransition(
      previousToken: _currentToken,
      nextToken: parsed.token,
    );
    if (!transition.changed) return false;
    _currentToken = transition.nextToken;
    if (transition.shouldDeleteStoredToken) {
      await _store.delete();
    } else {
      await _store.write(transition.nextToken!);
    }
    await _consumer.setAuthToken(transition.nextToken);
    return true;
  });

  Future<bool> reject(String rejectedToken) => _serialize(() async {
    if (!shouldRejectUaDimAuthToken(
      currentToken: _currentToken,
      rejectedToken: rejectedToken,
    )) {
      return false;
    }
    _currentToken = null;
    await _consumer.setAuthToken(null);
    await _store.delete();
    return true;
  });

  Future<T> _serialize<T>(Future<T> Function() operation) async {
    final previous = _operation;
    final completed = Completer<void>();
    _operation = completed.future;
    try {
      await previous;
      return await operation();
    } finally {
      completed.complete();
    }
  }
}

const String uaDimAuthSnapshotScript = '''
(() => JSON.stringify({
  sessionToken: window.sessionStorage.getItem('uaDim.authToken'),
  localToken: window.localStorage.getItem('uaDim.authToken'),
  hasCurrentUser: Boolean(window.localStorage.getItem('uaDim.currentUser')),
}))();
''';

String uaDimApplyAuthRestoreScript(UaDimAuthRestorePlan plan) =>
    '''
(() => {
  const sessionToken = ${jsonEncode(plan.sessionToken)};
  const localToken = ${jsonEncode(plan.localToken)};
  const clearCurrentUser = ${plan.clearCurrentUser};
  if (sessionToken) {
    window.sessionStorage.setItem('uaDim.authToken', sessionToken);
  } else {
    window.sessionStorage.removeItem('uaDim.authToken');
  }
  if (localToken) {
    window.localStorage.setItem('uaDim.authToken', localToken);
  } else {
    window.localStorage.removeItem('uaDim.authToken');
  }
  if (clearCurrentUser) {
    window.localStorage.removeItem('uaDim.currentUser');
  }
})();
''';

const String uaDimInstallAuthBridgeScript = '''
(() => {
  if (window.__uaDimAuthBridgeInstalled) return;
  window.__uaDimAuthBridgeInstalled = true;
  let previous = null;
  const syncAuth = () => {
    const token = window.sessionStorage.getItem('uaDim.authToken')
      || window.localStorage.getItem('uaDim.authToken')
      || '';
    const payload = JSON.stringify({
      version: 1,
      type: 'auth',
      token: token || null,
    });
    if (payload === previous) return;
    previous = payload;
    UaDimAuth.postMessage(payload);
  };
  window.addEventListener('storage', syncAuth);
  window.setInterval(syncAuth, 1500);
  syncAuth();
})();
''';
