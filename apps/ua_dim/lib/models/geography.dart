const List<String> uaRegions = [
  'Вінницька',
  'Волинська',
  'Дніпропетровська',
  'Донецька',
  'Житомирська',
  'Закарпатська',
  'Запорізька',
  'Івано-Франківська',
  'Київська',
  'Кіровоградська',
  'Луганська',
  'Львівська',
  'Миколаївська',
  'Одеська',
  'Полтавська',
  'Рівненська',
  'Сумська',
  'Тернопільська',
  'Харківська',
  'Херсонська',
  'Хмельницька',
  'Черкаська',
  'Чернівецька',
  'Чернігівська',
  'Автономна Республіка Крим',
];

const Map<String, List<String>> uaRegionSettlements = {
  'Вінницька': ['Вінниця', 'Гайсин', 'Жмеринка', 'Могилів-Подільський', 'Тульчин', 'Хмільник', 'Козятин', 'Ладижин'],
  'Волинська': ['Луцьк', 'Володимир', 'Камінь-Каширський', 'Ковель', 'Нововолинськ', 'селище Маневичі'],
  'Дніпропетровська': ['Дніпро', 'Кам\'янське', 'Кривий Ріг', 'Нікополь', 'Павлоград', 'Самар', 'Синельникове', 'Жовті Води'],
  'Донецька': ['Донецьк', 'Бахмут', 'Волноваха', 'Горлівка', 'Кальміуське', 'Краматорськ', 'Маріуполь', 'Покровськ', 'Слов\'янськ'],
  'Житомирська': ['Житомир', 'Бердичів', 'Звягель', 'Коростень', 'Коростишів', 'Малин'],
  'Закарпатська': ['Ужгород', 'Берегове', 'Мукачево', 'Рахів', 'Тячів', 'Хуст', 'Виноградів', 'Свалява'],
  'Запорізька': ['Запоріжжя', 'Бердянськ', 'Василівка', 'Мелітополь', 'Пологи', 'Енергодар', 'Токмак'],
  'Івано-Франківська': ['Івано-Франківськ', 'Калуш', 'Коломия', 'Косів', 'Надвірна', 'Яремче', 'селище Верховина', 'селище Поляниця'],
  'Київська': ['Київ', 'Біла Церква', 'Бориспіль', 'Бровари', 'Буча', 'Вишгород', 'Обухів', 'Фастів', 'Ірпінь', 'Васильків', 'Вишневе', 'селище Гостомель'],
  'Кіровоградська': ['Кропивницький', 'Новоукраїнка', 'Олександрія', 'Світловодськ', 'Знам\'янка', 'селище Голованівськ'],
  'Луганська': ['Луганськ', 'Алчевськ', 'Довжанськ', 'Ровеньки', 'Сватове', 'Старобільськ', 'Сіверськодонецьк', 'Щастя', 'Лисичанськ'],
  'Львівська': ['Львів', 'Дрогобич', 'Золочів', 'Самбір', 'Стрий', 'Шептицький', 'Яворів', 'Трускавець', 'Борислав', 'селище Славське'],
  'Миколаївська': ['Миколаїв', 'Баштанка', 'Вознесенськ', 'Первомайськ', 'Южноукраїнськ', 'Очаків'],
  'Одеська': ['Одеса', 'Березівка', 'Білгород-Дністровський', 'Болград', 'Ізмаїл', 'Подільськ', 'Роздільна', 'Чорноморськ', 'селище Затока'],
  'Полтавська': ['Полтава', 'Кременчук', 'Лубни', 'Миргород', 'Горішні Плавні', 'Гадяч'],
  'Рівненська': ['Рівне', 'Вараш', 'Дубно', 'Сарни', 'Костопіль', 'Здолбунів'],
  'Сумська': ['Суми', 'Конотоп', 'Охтирка', 'Ромни', 'Шостка', 'Глухів', 'Лебедин'],
  'Тернопільська': ['Тернопіль', 'Кременець', 'Чортків', 'Бережани', 'Бучач', 'Заліщики'],
  'Харківська': ['Харків', 'Богодухів', 'Ізюм', 'Красноград', 'Куп\'янськ', 'Лозова', 'Чугуїв', 'Балаклія'],
  'Херсонська': ['Херсон', 'Берислав', 'Генічеськ', 'Каховка', 'Нова Каховка', 'Скадовськ', 'Олешки'],
  'Хмельницька': ['Хмельницький', 'Кам\'янець-Подільський', 'Шепетівка', 'Нетішин', 'Славута', 'Старокостянтинів'],
  'Черкаська': ['Черкаси', 'Звенигородка', 'Золотоноша', 'Умань', 'Сміла', 'Канів'],
  'Чернівецька': ['Чернівці', 'Вижниця', 'Новодністровськ', 'Хотин', 'Сторожинець', 'селище Кельменці'],
  'Чернігівська': ['Чернігів', 'Корюківка', 'Ніжин', 'Новгород-Сіверський', 'Прилуки', 'Бахмач'],
  'Автономна Республіка Крим': ['Сімферополь', 'Севастополь', 'Євпаторія', 'Бахчисарай', 'Білогірськ', 'Джанкой', 'Керч', 'Феодосія', 'Ялта', 'Алушта'],
};

final Map<String, String> _cityToRegionMap = () {
  final map = <String, String>{
    'київ': 'Київська',
    'львів': 'Львівська',
    'одеса': 'Одеська',
    'харків': 'Харківська',
    'дніпро': 'Дніпропетровська',
    'вінниця': 'Вінницька',
    'запоріжжя': 'Запорізька',
    'івано-франківськ': 'Івано-Франківська',
    'ужгород': 'Закарпатська',
    'чернівці': 'Чернівецька',
    'житомир': 'Житомирська',
    'полтава': 'Полтавська',
    'рівне': 'Рівненська',
    'суми': 'Сумська',
    'тернопіль': 'Тернопільська',
    'херсон': 'Херсонська',
    'хмельницький': 'Хмельницька',
    'черкаси': 'Черкаська',
    'чернігів': 'Чернігівська',
    'кропивницький': 'Кіровоградська',
    'миколаїв': 'Миколаївська',
    'луцьк': 'Волинська',
    'донецьк': 'Донецька',
    'луганськ': 'Луганська',
    'сімферополь': 'Автономна Республіка Крим',
    'севастополь': 'Автономна Республіка Крим',
  };
  for (final entry in uaRegionSettlements.entries) {
    for (final settlement in entry.value) {
      final key = settlement.toLowerCase().replaceAll(RegExp(r'^(селище|село|м\.|смт)\s+', caseSensitive: false), '').trim();
      map.putIfAbsent(key, () => entry.key);
      map.putIfAbsent(settlement.toLowerCase(), () => entry.key);
    }
  }
  return map;
}();

class UaGeography {
  const UaGeography._();

  static String normalizeRegion(String? raw) {
    final text = raw?.trim() ?? '';
    if (text.isEmpty) return '';
    final cleaned = text
        .replaceAll(RegExp(r'\s+область$', caseSensitive: false), '')
        .replaceAll(RegExp(r'\s+обл\.?$', caseSensitive: false), '')
        .trim();
    for (final region in uaRegions) {
      if (region.toLowerCase() == cleaned.toLowerCase() ||
          region.toLowerCase() == text.toLowerCase()) {
        return region;
      }
    }
    return cleaned;
  }

  static String formatRegionLabel(String? region) {
    if (region == null || region.isEmpty || region == 'Всі') {
      return 'Всі області України';
    }
    if (region == 'Автономна Республіка Крим') return region;
    return '$region область';
  }

  static String inferRegionForCity(String? city) {
    if (city == null || city.trim().isEmpty) return '';
    final raw = city.trim().toLowerCase();
    final stripped = raw.replaceAll(RegExp(r'^(селище|село|м\.|смт)\s+', caseSensitive: false), '').trim();
    return _cityToRegionMap[raw] ?? _cityToRegionMap[stripped] ?? '';
  }

  static List<String> getSettlementsForRegion(String? region) {
    final norm = normalizeRegion(region);
    return uaRegionSettlements[norm] ?? const [];
  }

  static bool isCityInRegion(String? city, String? region) {
    if (region == null || region.isEmpty || region == 'Всі') return true;
    if (city == null || city.isEmpty) return false;
    final normRegion = normalizeRegion(region);
    final inferred = inferRegionForCity(city);
    if (inferred.isNotEmpty && inferred.toLowerCase() == normRegion.toLowerCase()) {
      return true;
    }
    final list = uaRegionSettlements[normRegion];
    if (list == null) return false;
    final target = city.trim().toLowerCase();
    return list.any((item) => item.toLowerCase() == target || item.toLowerCase().contains(target));
  }
}

class UaSearchLocationFilter {
  const UaSearchLocationFilter({
    this.region,
    this.city,
  });

  final String? region;
  final String? city;

  bool get hasFilter => (region != null && region!.isNotEmpty && region != 'Всі') ||
      (city != null && city!.isNotEmpty && city != 'Всі');

  Map<String, String> toQueryParameters() {
    final params = <String, String>{};
    if (region != null && region!.isNotEmpty && region != 'Всі') {
      params['region'] = region!;
    }
    if (city != null && city!.isNotEmpty && city != 'Всі') {
      params['city'] = city!;
    }
    return params;
  }

  Uri buildSearchUri({String baseUrl = 'https://ua-dim.com/app'}) {
    final baseUri = Uri.parse(baseUrl);
    final query = Map<String, String>.from(baseUri.queryParameters)
      ..addAll(toQueryParameters());
    return baseUri.replace(queryParameters: query);
  }

  static UaSearchLocationFilter fromUri(Uri uri) {
    final region = uri.queryParameters['region'];
    final city = uri.queryParameters['city'] ?? uri.queryParameters['settlement'];
    return UaSearchLocationFilter(
      region: region != null ? UaGeography.normalizeRegion(region) : null,
      city: city?.trim(),
    );
  }
}
