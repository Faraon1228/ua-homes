// ignore_for_file: deprecated_member_use, avoid_web_libraries_in_flutter
import 'dart:html' as html;

import 'package:flutter/material.dart';

class RealEstateDemoScreen extends StatefulWidget {
  const RealEstateDemoScreen({super.key});

  @override
  State<RealEstateDemoScreen> createState() => _RealEstateDemoScreenState();
}

class _RealEstateDemoScreenState extends State<RealEstateDemoScreen> {
  static const String _siteUrl =
      'https://ua-dim.com/real-estate-demo.html?source=flutter-web';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      html.window.location.assign(_siteUrl);
    });
  }

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: Color(0xFFF1F5F9),
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(color: Color(0xFF2563EB)),
            SizedBox(height: 16),
            Text(
              'Відкриваємо UA-Dim…',
              style: TextStyle(
                color: Color(0xFF0F172A),
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
