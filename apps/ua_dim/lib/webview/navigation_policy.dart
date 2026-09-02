const Set<String> uaDimProductionHosts = {'ua-dim.com', 'www.ua-dim.com'};

enum UaDimNavigationTarget { internal, external }

class UaDimNavigationPolicy {
  const UaDimNavigationPolicy({this.allowedHosts = uaDimProductionHosts});

  final Set<String> allowedHosts;

  UaDimNavigationTarget classify(Uri uri) {
    final isWebScheme = uri.scheme == 'http' || uri.scheme == 'https';
    return isWebScheme && allowedHosts.contains(uri.host.toLowerCase())
        ? UaDimNavigationTarget.internal
        : UaDimNavigationTarget.external;
  }

  bool isInternal(Uri uri) => classify(uri) == UaDimNavigationTarget.internal;

  bool isListing(Uri uri) {
    if (!isInternal(uri) || uri.pathSegments.length != 2) return false;
    return uri.pathSegments.first == 'listing' &&
        int.tryParse(uri.pathSegments.last) != null;
  }

  Uri? parseNativeListing(Object? value) {
    if (value is! String || value.trim().isEmpty) return null;
    var uri = Uri.tryParse(value.trim());
    if (uri?.scheme == 'uadim' && uri?.host == 'listing') {
      final listingId = uri!.pathSegments.firstOrNull;
      if (listingId == null) return null;
      uri = Uri.parse('https://ua-dim.com/listing/$listingId');
    }
    return uri != null && isListing(uri) ? uri : null;
  }
}
