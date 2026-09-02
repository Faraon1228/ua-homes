# Google Play Data Safety draft (based on current repo behavior)

Scope note: this draft is grounded in `apps/ua_dim` code and current legal pages (`/privacy.html`, `/cookie-policy.html`, `/terms.html`). Mark as draft until owner confirms production backend settings.

## Data collected

1. **Personal info**
   - Name
   - Email address
   - Phone number (optional, with verification status)
2. **User content**
   - Listing text/content submitted by sellers
   - Listing photos/videos uploaded by sellers
3. **App activity**
   - In-app interactions related to search/favorites/listing usage
4. **App info and performance**
   - Diagnostics/performance/error telemetry
5. **Device or other IDs**
   - Push token / pseudonymous session identifiers

## Data sharing (Google Play definition caution)

Data can involve third-party processors used to operate the product:
- Hosting and infrastructure providers
- Media storage provider
- Analytics provider (after consent)
- Messaging/email/SMS providers

Important: in Google Play Data Safety, whether this is "shared" depends on Play's specific definition and exemptions (for example, service-provider processing on behalf of the developer may be treated differently than broader third-party sharing).  
This repository alone is not enough to finalize the legal classification for every processor and data type.

No evidence in repo of selling personal data to data brokers.

## Required Play Console questionnaire direction (draft)

1. **Is data collected?** → Yes
2. **Is data shared?** → **TBD after processor-by-processor assessment against Google Play definitions/exemptions**
3. **Is all data encrypted in transit?** → Yes (HTTPS endpoints)
4. **Can users request data deletion?** → Yes (manual request via contacts in privacy policy)
5. **Collection purposes likely applicable:**
   - App functionality
   - Account management
   - Analytics (consent-gated)
   - Fraud prevention, security, and compliance
   - Developer communications

## Evidence anchors

- `apps/ua_dim/lib/screens/ua_dim_screen.dart` (auth token handling, web session bridge)
- `apps/ua_dim/lib/services/mobile_push_service.dart` (Firebase messaging token registration)
- `apps/ua_dim/android/app/src/main/AndroidManifest.xml` (internet + notifications permissions)
- `web/privacy.html` (declared data categories, processors, retention, rights)
- `web/cookie-policy.html` (consent-gated analytics + storage behavior)

## Owner confirmation needed before submission

- Confirm whether precise location is collected in production (not asserted by app shell code).
- Confirm whether any payment flow is active for mobile users at launch.
- Confirm exact retention windows for push-device identifiers.
- Confirm whether analytics is always consent-gated in the mobile path as in web policy.
- Confirm each processor/data-flow against Google Play "shared" vs exempt service-provider handling before selecting a final Yes/No in Console.
