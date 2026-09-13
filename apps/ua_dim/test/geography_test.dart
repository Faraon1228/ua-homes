import 'package:flutter_test/flutter_test.dart';
import 'package:ua_dim/models/geography.dart';
import 'package:ua_dim/webview/navigation_policy.dart';

void main() {
  group('UaGeography tests', () {
    test('contains all 25 Ukrainian regions including Crimea', () {
      expect(uaRegions.length, 25);
      expect(uaRegions, contains('Київська'));
      expect(uaRegions, contains('Львівська'));
      expect(uaRegions, contains('Одеська'));
      expect(uaRegions, contains('Харківська'));
      expect(uaRegions, contains('Дніпропетровська'));
      expect(uaRegions, contains('Автономна Республіка Крим'));
    });

    test('normalizes region names with oblast suffixes', () {
      expect(UaGeography.normalizeRegion('Київська область'), 'Київська');
      expect(UaGeography.normalizeRegion('Львівська обл.'), 'Львівська');
      expect(UaGeography.normalizeRegion('  Одеська  '), 'Одеська');
      expect(UaGeography.normalizeRegion('Автономна Республіка Крим'), 'Автономна Республіка Крим');
      expect(UaGeography.normalizeRegion(''), '');
      expect(UaGeography.normalizeRegion(null), '');
    });

    test('formats region labels for UI selectors', () {
      expect(UaGeography.formatRegionLabel('Київська'), 'Київська область');
      expect(UaGeography.formatRegionLabel('Автономна Республіка Крим'), 'Автономна Республіка Крим');
      expect(UaGeography.formatRegionLabel('Всі'), 'Всі області України');
      expect(UaGeography.formatRegionLabel(null), 'Всі області України');
    });

    test('infers region from Ukrainian city and settlement names', () {
      expect(UaGeography.inferRegionForCity('Київ'), 'Київська');
      expect(UaGeography.inferRegionForCity('Біла Церква'), 'Київська');
      expect(UaGeography.inferRegionForCity('Буча'), 'Київська');
      expect(UaGeography.inferRegionForCity('Львів'), 'Львівська');
      expect(UaGeography.inferRegionForCity('Дрогобич'), 'Львівська');
      expect(UaGeography.inferRegionForCity('Одеса'), 'Одеська');
      expect(UaGeography.inferRegionForCity('Харків'), 'Харківська');
      expect(UaGeography.inferRegionForCity('Дніпро'), 'Дніпропетровська');
      expect(UaGeography.inferRegionForCity('Кривий Ріг'), 'Дніпропетровська');
      expect(UaGeography.inferRegionForCity('Вінниця'), 'Вінницька');
      expect(UaGeography.inferRegionForCity('Івано-Франківськ'), 'Івано-Франківська');
      expect(UaGeography.inferRegionForCity('селище Верховина'), 'Івано-Франківська');
      expect(UaGeography.inferRegionForCity('Сімферополь'), 'Автономна Республіка Крим');
      expect(UaGeography.inferRegionForCity('НевідомеМісто123'), '');
    });

    test('validates city within region mapping', () {
      expect(UaGeography.isCityInRegion('Київ', 'Київська'), isTrue);
      expect(UaGeography.isCityInRegion('Бровари', 'Київська'), isTrue);
      expect(UaGeography.isCityInRegion('Львів', 'Київська'), isFalse);
      expect(UaGeography.isCityInRegion('Львів', 'Львівська'), isTrue);
      expect(UaGeography.isCityInRegion('Будь-яке', 'Всі'), isTrue);
      expect(UaGeography.isCityInRegion('Будь-яке', null), isTrue);
    });

    test('returns settlements list for specific region', () {
      final kyivSettlements = UaGeography.getSettlementsForRegion('Київська');
      expect(kyivSettlements, contains('Київ'));
      expect(kyivSettlements, contains('Біла Церква'));
      expect(kyivSettlements, contains('Буча'));
      expect(kyivSettlements, isNot(contains('Львів')));

      final lvivSettlements = UaGeography.getSettlementsForRegion('Львівська');
      expect(lvivSettlements, contains('Львів'));
      expect(lvivSettlements, contains('Дрогобич'));
      expect(lvivSettlements, isNot(contains('Київ')));
    });

    test('UaSearchLocationFilter builds search URIs and parses query params', () {
      const filter = UaSearchLocationFilter(
        region: 'Київська',
        city: 'Буча',
      );
      expect(filter.hasFilter, isTrue);
      final uri = filter.buildSearchUri();
      expect(uri.host, 'ua-dim.com');
      expect(uri.queryParameters['region'], 'Київська');
      expect(uri.queryParameters['city'], 'Буча');

      final parsed = UaSearchLocationFilter.fromUri(uri);
      expect(parsed.region, 'Київська');
      expect(parsed.city, 'Буча');
    });

    test('UaDimNavigationPolicy parses native search deep links with region and city', () {
      const policy = UaDimNavigationPolicy();
      final uri = policy.parseNativeSearch('uadim://search?region=Київська&city=Буча');
      expect(uri, isNotNull);
      expect(uri?.host, 'ua-dim.com');
      expect(uri?.path, '/app');
      expect(uri?.queryParameters['region'], 'Київська');
      expect(uri?.queryParameters['city'], 'Буча');
    });
  });
}
