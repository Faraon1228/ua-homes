import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

const String uaDimProductionUrl =
    'https://ua-dim.com/real-estate-demo.html'
    '?source=ua-dim-app&release=20260814-native-links';
const MethodChannel _nativeChannel = MethodChannel('com.uadim.app/native');

bool isUaDimInternalUri(Uri uri) {
  if (uri.scheme != 'http' && uri.scheme != 'https') return false;
  return uri.host == 'ua-dim.com' || uri.host.endsWith('.ua-dim.com');
}

bool isUaDimListingUri(Uri uri) {
  if (!isUaDimInternalUri(uri) || uri.pathSegments.length != 2) return false;
  return uri.pathSegments.first == 'listing' &&
      int.tryParse(uri.pathSegments.last) != null;
}

Uri? parseUaDimNativeUri(Object? value) {
  if (value is! String || value.trim().isEmpty) return null;
  final uri = Uri.tryParse(value.trim());
  return uri != null && isUaDimListingUri(uri) ? uri : null;
}

class UaDimScreen extends StatefulWidget {
  const UaDimScreen({super.key});

  @override
  State<UaDimScreen> createState() => _UaDimScreenState();
}

class _UaDimScreenState extends State<UaDimScreen> {
  late final WebViewController _controller;
  bool _isLoading = true;
  bool _canGoBack = false;
  String? _loadError;
  Uri _currentUri = Uri.parse(uaDimProductionUrl);
  String _pageTitle = 'UA-Dim';

  bool get _supportsAndroidNativeIntegration =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  bool get _canShareCurrentPage =>
      _supportsAndroidNativeIntegration && isUaDimListingUri(_currentUri);

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
          onPageFinished: (url) async {
            if (!mounted) return;
            final canGoBack = await _controller.canGoBack();
            final title = await _controller.getTitle();
            if (!mounted) return;
            setState(() {
              _isLoading = false;
              _canGoBack = canGoBack;
              _currentUri = Uri.tryParse(url) ?? _currentUri;
              _pageTitle = title?.trim().isNotEmpty == true
                  ? title!.trim()
                  : 'UA-Dim';
            });
          },
          onWebResourceError: (error) {
            if (error.isForMainFrame != true || !mounted) return;
            setState(() {
              _isLoading = false;
              _loadError = error.description;
            });
          },
          onNavigationRequest: _handleNavigationRequest,
        ),
      )
      ..loadRequest(Uri.parse(uaDimProductionUrl));
    _configureNativeIntegration();
    _configureAndroidFileSelector();
  }

  Future<void> _configureAndroidFileSelector() async {
    final platformController = _controller.platform;
    if (!_supportsAndroidNativeIntegration ||
        platformController is! AndroidWebViewController) {
      return;
    }
    try {
      await platformController.setOnShowFileSelector(_selectAndroidFiles);
    } on PlatformException catch (error) {
      debugPrint('UA-Dim Android file selector unavailable: ${error.message}');
    }
  }

  Future<List<String>> _selectAndroidFiles(FileSelectorParams params) async {
    try {
      return await _nativeChannel.invokeListMethod<String>('pickFiles', {
            'acceptTypes': params.acceptTypes,
            'allowMultiple': params.mode == FileSelectorMode.openMultiple,
            'capture': params.isCaptureEnabled,
          }) ??
          const [];
    } on PlatformException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(error.message ?? 'Не вдалося обрати медіафайл'),
          ),
        );
      }
      return const [];
    }
  }

  Future<void> _configureNativeIntegration() async {
    if (!_supportsAndroidNativeIntegration) return;
    _nativeChannel.setMethodCallHandler((call) async {
      if (call.method != 'openUrl') return;
      final uri = parseUaDimNativeUri(call.arguments);
      if (uri != null) await _openInternalUri(uri);
    });

    try {
      final initialUrl = await _nativeChannel.invokeMethod<String>(
        'getInitialUrl',
      );
      final uri = parseUaDimNativeUri(initialUrl);
      if (uri != null) await _openInternalUri(uri);
    } on PlatformException catch (error) {
      debugPrint('UA-Dim native launch URL unavailable: ${error.message}');
    }
  }

  Future<void> _openInternalUri(Uri uri) async {
    if (!isUaDimInternalUri(uri)) return;
    if (mounted) {
      setState(() {
        _isLoading = true;
        _loadError = null;
      });
    }
    await _controller.loadRequest(uri);
  }

  Future<void> _shareCurrentPage() async {
    if (!_canShareCurrentPage) return;
    try {
      await _nativeChannel.invokeMethod<void>('share', {
        'subject': _pageTitle,
        'text': '$_pageTitle\n$_currentUri',
      });
    } on PlatformException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            error.message ?? 'Не вдалося поділитися оголошенням',
          ),
        ),
      );
    }
  }

  Future<NavigationDecision> _handleNavigationRequest(
    NavigationRequest request,
  ) async {
    final uri = Uri.tryParse(request.url);
    if (uri != null && isUaDimInternalUri(uri)) {
      return NavigationDecision.navigate;
    }

    final launched =
        uri != null &&
        await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!launched && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Не вдалося відкрити посилання')),
      );
    }
    return NavigationDecision.prevent;
  }

  Future<void> _goBack() async {
    if (!_canGoBack) return;
    await _controller.goBack();
    final canGoBack = await _controller.canGoBack();
    if (!mounted) return;
    setState(() => _canGoBack = canGoBack);
  }

  void _retry() {
    setState(() {
      _isLoading = true;
      _loadError = null;
    });
    _controller.loadRequest(Uri.parse(uaDimProductionUrl));
  }

  @override
  void dispose() {
    if (_supportsAndroidNativeIntegration) {
      _nativeChannel.setMethodCallHandler(null);
      final platformController = _controller.platform;
      if (platformController is AndroidWebViewController) {
        platformController.setOnShowFileSelector(null);
      }
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !_canGoBack,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _goBack();
      },
      child: Scaffold(
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
              if (_canShareCurrentPage && !_isLoading && _loadError == null)
                Positioned(
                  right: 16,
                  bottom: 16,
                  child: FloatingActionButton.small(
                    heroTag: 'share-listing',
                    onPressed: _shareCurrentPage,
                    tooltip: 'Поділитися оголошенням',
                    child: const Icon(Icons.share_outlined),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
