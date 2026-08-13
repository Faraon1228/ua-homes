// This is a basic Flutter widget test.
//
// It is used to verify that the main application builds correctly.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:hive/hive.dart';
import 'package:drive_community/main.dart';
import 'package:drive_community/models/adapters.dart';

void main() {
  setUpAll(() async {
    final tempDir = await Directory.systemTemp.createTemp('hive_test_');
    Hive.init(tempDir.path);
    Hive.registerAdapter(StoryAdapter());
    Hive.registerAdapter(ChatMessageAdapter());
    Hive.registerAdapter(ChatThreadAdapter());
  });

  tearDownAll(() async {
    await Hive.close();
  });

  testWidgets('App loads home screen and profile tab works', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const DriveCommunityApp());
    await tester.pump();

    for (var i = 0; i < 20; i++) {
      if (find.text('DriveCommunity').evaluate().isNotEmpty) {
        break;
      }
      await tester.pump(const Duration(milliseconds: 100));
    }

    expect(find.text('DriveCommunity'), findsOneWidget);
    expect(find.text('Головна'), findsOneWidget);
    expect(find.text('Житло'), findsNothing);

    await tester.tap(find.text('Профіль'));
    await tester.pump();

    for (var i = 0; i < 20; i++) {
      if (find.text('Олександр_R1').evaluate().isNotEmpty) {
        break;
      }
      await tester.pump(const Duration(milliseconds: 100));
    }

    expect(find.text('Профіль'), findsWidgets);
    expect(find.text('Олександр_R1'), findsOneWidget);
  });
}
