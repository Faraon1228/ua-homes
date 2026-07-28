import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

class RealEstateDemoScreen extends StatefulWidget {
  const RealEstateDemoScreen({super.key});

  @override
  State<RealEstateDemoScreen> createState() => _RealEstateDemoScreenState();
}

class _RealEstateDemoScreenState extends State<RealEstateDemoScreen> {
  late final WebViewController _controller;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (_) => setState(() => _isLoading = true),
          onPageFinished: (_) => setState(() => _isLoading = false),
        ),
      )
      ..loadFlutterAsset('web/real-estate-demo.html');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Real Estate Demo'),
        backgroundColor: const Color(0xFF0F172A),
      ),
      body: Stack(
        children: [
          WebViewWidget(controller: _controller),
          if (_isLoading)
            const Center(
              child: CircularProgressIndicator(color: Colors.blueAccent),
            ),
        ],
      ),
    );
  }
}
