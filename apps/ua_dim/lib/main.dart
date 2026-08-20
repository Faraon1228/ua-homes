import 'package:flutter/material.dart';
import 'package:sentry_flutter/sentry_flutter.dart';

import 'screens/ua_dim_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  const dsn = String.fromEnvironment('UA_DIM_SENTRY_DSN');
  if (dsn.isEmpty) {
    runApp(const UaDimApp());
    return;
  }
  await SentryFlutter.init((options) {
    options
      ..dsn = dsn
      ..tracesSampleRate = 0.1
      ..sendDefaultPii = false;
  }, appRunner: () => runApp(SentryWidget(child: const UaDimApp())));
}

class UaDimApp extends StatelessWidget {
  const UaDimApp({super.key, this.home});

  final Widget? home;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'UA-Dim',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF2563EB),
          surface: const Color(0xFFF1F5F9),
        ),
        scaffoldBackgroundColor: const Color(0xFFF1F5F9),
        useMaterial3: true,
      ),
      home: home ?? const UaDimScreen(),
    );
  }
}
