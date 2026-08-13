import 'package:flutter/material.dart';

import 'screens/ua_dim_screen.dart';

void main() {
  runApp(const UaDimApp());
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
