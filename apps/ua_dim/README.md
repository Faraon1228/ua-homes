# UA-Dim mobile

Standalone iOS and Android shell for the UA-Dim real-estate product.

The app loads the canonical production experience from
`https://ua-dim.com/app?source=ua-dim-app&release=20260820-photo-library`, so search,
seller tools, uploads and listing details use the same frontend and API release
as the website.

The silver homepage skyline is part of that shared web shell: publish the rebuilt
`web/` assets through the existing website release workflow, then reload the app
online to receive it. No Flutter binary change or store release is needed for
this decoration. Its one-time CSS reveal respects reduced motion; on narrow
screens the SVG keeps its aspect ratio. The artwork is versioned and precached
with the shell, rather than retained in the listing-photo cache. Offline devices
continue using their previously cached release until they reconnect.

For the shared homepage browser regressions, run from the repository root:

```bash
npm run test:admin -- tests/admin/homepage-buildings.spec.js tests/admin/homepage-buildings-cache.spec.js
npx playwright install webkit
UA_TEST_WEBKIT=1 npm run test:admin -- tests/admin/homepage-buildings.spec.js --project=desktop-webkit --project=mobile-webkit
```

WebKit and mobile viewport tests check the web UI, not the actual native app or
its authentication/media bridges; device testing remains a separate release check.

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
