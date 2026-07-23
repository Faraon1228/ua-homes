import 'dart:io';

String getRemoteBaseUrl() {
  if (Platform.isAndroid) {
    return 'http://10.0.2.2:8080';
  }
  return 'http://localhost:8080';
}
