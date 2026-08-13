# UA-Dim mobile

Standalone iOS and Android shell for the UA-Dim real-estate product.

The app loads the canonical production experience from
`https://ua-dim.com/real-estate-demo.html?source=ua-dim-app`, so search,
seller tools, uploads and listing details use the same frontend and API release
as the website.

## Commands

```bash
flutter pub get
flutter analyze lib test
flutter test
flutter build apk --release
flutter build ios --release --no-codesign
```

Application identity:

- Android application ID: `com.uadim.app`
- iOS bundle ID: `com.uadim.app`
- Display name: `UA-Dim`
