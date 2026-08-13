import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

const String uaDimProductionUrl =
    'https://ua-dim.com/real-estate-demo.html?source=ua-dim-app';

class UaDimScreen extends StatefulWidget {
  const UaDimScreen({super.key});

  @override
  State<UaDimScreen> createState() => _UaDimScreenState();
}

class _UaDimScreenState extends State<UaDimScreen> {
  late final WebViewController _controller;
  bool _isLoading = true;
  String? _loadError;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFFF1F5F9))
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (_) {
            if (!mounted) return;
            setState(() {
              _isLoading = true;
              _loadError = null;
            });
          },
          onPageFinished: (_) {
            if (!mounted) return;
            setState(() => _isLoading = false);
          },
          onWebResourceError: (error) {
            if (error.isForMainFrame != true || !mounted) return;
            setState(() {
              _isLoading = false;
              _loadError = error.description;
            });
          },
        ),
      )
      ..loadRequest(Uri.parse(uaDimProductionUrl));
  }

  void _retry() {
    setState(() {
      _isLoading = true;
      _loadError = null;
    });
    _controller.loadRequest(Uri.parse(uaDimProductionUrl));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF1F5F9),
      body: SafeArea(
        child: Stack(
          children: [
            WebViewWidget(controller: _controller),
            if (_loadError != null)
              ColoredBox(
                color: const Color(0xFFF1F5F9),
                child: Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(
                          Icons.cloud_off_outlined,
                          size: 48,
                          color: Color(0xFF334155),
                        ),
                        const SizedBox(height: 16),
                        const Text(
                          'Не вдалося відкрити UA-Dim',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Color(0xFF0F172A),
                            fontSize: 20,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          _loadError!,
                          maxLines: 3,
                          overflow: TextOverflow.ellipsis,
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: Color(0xFF475569)),
                        ),
                        const SizedBox(height: 20),
                        FilledButton.icon(
                          onPressed: _retry,
                          icon: const Icon(Icons.refresh),
                          label: const Text('Спробувати ще раз'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            if (_isLoading)
              ColoredBox(
                color: const Color(0xFFF1F5F9),
                child: Center(
                  child: Semantics(
                    label: 'UA-Dim завантажується',
                    child: const CircularProgressIndicator(
                      color: Color(0xFF2563EB),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
