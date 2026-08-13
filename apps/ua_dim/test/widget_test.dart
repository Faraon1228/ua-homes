import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ua_dim/main.dart';
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
    expect(uaDimProductionUrl, contains('source=ua-dim-app'));
    expect(uaDimProductionUrl, contains('release=20260813-seller-detail'));
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
}
