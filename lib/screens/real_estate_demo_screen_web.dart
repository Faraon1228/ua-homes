// ignore_for_file: deprecated_member_use, avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';

class RealEstateDemoScreen extends StatefulWidget {
  const RealEstateDemoScreen({super.key});

  @override
  State<RealEstateDemoScreen> createState() => _RealEstateDemoScreenState();
}

class _RealEstateDemoScreenState extends State<RealEstateDemoScreen> {
  static const String _viewType = 'real-estate-demo-view';

  @override
  void initState() {
    super.initState();
    ui_web.platformViewRegistry.registerViewFactory(_viewType, (int viewId) {
      final iframe = html.IFrameElement()
        ..src = 'real-estate-demo.html'
        ..style.border = 'none'
        ..style.width = '100%'
        ..style.height = '100%';
      return iframe;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Real Estate Demo'),
        backgroundColor: const Color(0xFF0F172A),
      ),
      body: const SizedBox.expand(
        child: HtmlElementView(viewType: _viewType),
      ),
    );
  }
}
