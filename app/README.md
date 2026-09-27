# Voice Analytics Flutter Client

## App overview

Flutter client for the Voice Analytics POC. The iOS app provides Firebase email/password authentication, single or multi-file audio selection, resumable TUS uploads, per-file upload progress, backend file and result listing, server-side filters, transcript and analysis display, optional Layer 2 configuration, and backend-provided guardrails.

## Flutter prerequisites

This checkout is configured for iOS only.

- Flutter 3.41.9 on the stable channel
- Dart 3.11.5 or a compatible Dart 3 release allowed by `sdk: ^3.11.5` in `pubspec.yaml`
- macOS with Xcode and an iOS 15.0 or newer Simulator runtime
- CocoaPods available to Flutter for iOS dependency installation

The current development environment uses Xcode 26.5 and CocoaPods 1.16.2. The project declares iOS 15.0 in `ios/Podfile` and `ios/Runner.xcodeproj/project.pbxproj`.

## Firebase client setup

The app initializes Firebase in `lib/main.dart` with `DefaultFirebaseOptions.currentPlatform` from the generated `lib/firebase_options.dart`. That generated file currently contains iOS configuration only.

The Firebase project must have:

- An iOS app registered with the Runner bundle identifier. The current identifier is `com.example.voiceAnalyticsAgenticAiPlatform`.
- Firebase Authentication enabled.
- Email/Password enabled under Authentication > Sign-in method.

The native Firebase configuration file must exist at:

```text
ios/Runner/GoogleService-Info.plist
```

It is already included in the Runner target resources. For a different Firebase project:

1. Replace `ios/Runner/GoogleService-Info.plist` with the plist downloaded for that project's iOS app.
2. Regenerate or replace `lib/firebase_options.dart` so `DefaultFirebaseOptions.ios` belongs to the same Firebase project and bundle identifier.
3. If the new Firebase iOS app uses another bundle identifier, update the Runner `PRODUCT_BUNDLE_IDENTIFIER` in `ios/Runner.xcodeproj/project.pbxproj` to match it.

The FlutterFire CLI can regenerate the Dart configuration when changing projects:

```bash
dart pub global activate flutterfire_cli
flutterfire configure --platforms=ios
```

No Android, web, macOS, Windows, or Linux Firebase options are configured.

## Backend connection configuration

Backend addresses are defined in `lib/services/api_config.dart` by these exact members:

```dart
ApiConfig.host
ApiConfig.fastApiBaseUrl
ApiConfig.tusdBaseUrl
```

The current values are derived as follows:

```text
BACKEND_HOST default: localhost
ApiConfig.fastApiBaseUrl: http://localhost:8000
ApiConfig.tusdBaseUrl: http://localhost:8081
TUS creation endpoint: http://localhost:8081/files/
```

These defaults work with FastAPI and tusd running on the same Mac as the iOS Simulator. To use another host while retaining plain HTTP and the same ports, pass the hostname without a scheme or port:

```bash
flutter run -d <simulator-device-id> --dart-define=BACKEND_HOST=backend-host
```

For a deployed backend using HTTPS, different ports, or separate FastAPI and tusd hosts, replace the values of `ApiConfig.fastApiBaseUrl` and `ApiConfig.tusdBaseUrl` in `lib/services/api_config.dart` with the required absolute URLs. The current `BACKEND_HOST` setting cannot express separate hosts, HTTPS, or custom ports. `ios/Runner/Info.plist` permits local HTTP through `NSAllowsLocalNetworking`; a deployed service should use HTTPS.

## Install dependencies

Runtime packages are declared in `pubspec.yaml`: `firebase_core`, `firebase_auth`, `tusc`, `file_picker`, and `path_provider`.

From the project root:

```bash
flutter pub get
```

Flutter invokes CocoaPods as part of the iOS build when needed. There are no additional app dependency setup commands.

## Run on an iOS Simulator

Start an installed iOS 15.0 or newer Simulator, list its Flutter device ID, and run the only configured entry point, `lib/main.dart`:

```bash
open -a Simulator
flutter devices
flutter run -d <simulator-device-id>
```

For the default local backend, do not pass `BACKEND_HOST`. There are no flavors or alternate launch configurations.

## Authentication flow

- Signup creates a Firebase email/password user and Firebase signs the new user in.
- Login uses Firebase email/password authentication.
- Firebase auth-state changes switch automatically between Login and the Main page.
- Logout is available from the Main page app bar and requires confirmation.
- `AuthService.credentials()` gets the current Firebase UID and ID token. Backend API requests and TUS uploads attach the token as `Authorization: Bearer <token>`.
- Email verification is not required by this POC.

## Upload flow

The Main page allows one or multiple audio files to be selected in one picker action. Each selection is staged locally and receives an independent TUS upload. Selected files are uploaded sequentially, each with its own progress and failure state; one failure does not stop the remaining files.

Resumability uses `TusPersistentCache`. Each local selection has a random persistent selection ID, a staged file, and a manifest under the app support directory. The TUS resume identity combines `ApiConfig.tusdBaseUrl`, the Firebase UID, and that selection ID, so files with the same name and size do not share a resume URL. Pending selections are restored and resumed after an app restart. Failed uploads expose a Retry action, and successful uploads remove the local selection manifest and cached resume mapping.

The TUS metadata includes the Firebase `user_id`, original `filename`, and, when selected, `layer2_options` and `layer2_config`. Available Layer 2 options are:

- `rms`
- `count_nouns`, with optional `unique_only`
- `count_adjectives`
- `sentiment`
- `topic_mentions`, with a required 1–100 character `topic`

The same predefined analyses can be added later from File Details when they have not already been selected.

## Backend interactions

All FastAPI requests below use the current Firebase bearer token:

| Request | Purpose |
| --- | --- |
| `GET /files` | List the authenticated user's files and apply selected query filters |
| `GET /files/{id}` | Load full details and processing status for one file |
| `GET /files/{id}/transcript` | Load the transcript when `transcript_available` is true |
| `POST /files/{id}/layer2` | Add newly selected Layer 2 analyses and configuration |
| `DELETE /files/{id}` | Delete a file owned by the authenticated user |
| `GET /guardrails` | Load the policy sections and current POC limits |

TUS uploads use `${ApiConfig.tusdBaseUrl}/files/`. The `tusc` client performs the TUS creation, resume, and chunk requests. Flutter does not call `/hooks/tusd` and does not send audio bytes to FastAPI.

## Filtering

The Filters page sends only non-empty values as `GET /files` query parameters. Filtering is performed by the backend.

| UI filter | Query parameter |
| --- | --- |
| Created from, ISO 8601 with timezone | `created_from` |
| Created to, ISO 8601 with timezone | `created_to` |
| Minimum duration in seconds | `duration_min` |
| Maximum duration in seconds | `duration_max` |
| Topic or event label | `taxonomy_label` |
| Sentiment: positive, neutral, or negative | `sentiment` |
| Minimum normalized RMS | `rms_min` |
| Maximum normalized RMS | `rms_max` |
| Minimum noun count | `noun_count_min` |
| Maximum noun count | `noun_count_max` |
| Minimum adjective count | `adjective_count_min` |
| Maximum adjective count | `adjective_count_max` |

Clear filters sends no filter query parameters.

## Results and guardrails UI

The file list shows processing status, duration when available, persisted backend errors, and Layer 1 results when available. File Details loads the latest file object and can display the transcript, summary, professional topics, personal topics, upcoming events, Layer 2 selections, configuration and results, processing versions, rejection information, and delete action. Active file states are polled every two seconds.

Guardrails are opened with the shield icon in the Main page app bar. The full-screen Guardrails page renders policy sections and limits returned by `GET /guardrails`; policy limits are not duplicated as Flutter constants. The Main page also builds its concise input hint from the returned guardrail data. Rejected files remain visible and show the backend-provided persisted rejection or error message.

## Configuration checklist for a new environment

- Replace `ios/Runner/GoogleService-Info.plist` with the new Firebase iOS app configuration.
- Regenerate or replace `lib/firebase_options.dart`, specifically `DefaultFirebaseOptions.ios`, for the same Firebase project.
- Enable Email/Password in Firebase Console under Authentication > Sign-in method.
- Verify the Firebase iOS bundle ID matches `PRODUCT_BUNDLE_IDENTIFIER` in `ios/Runner.xcodeproj/project.pbxproj`.
- Set the FastAPI address through `ApiConfig.fastApiBaseUrl` in `lib/services/api_config.dart`. The local default is `http://localhost:8000`.
- Set the tusd address through `ApiConfig.tusdBaseUrl` in `lib/services/api_config.dart`. The local default is `http://localhost:8081`.
- Run `flutter pub get`.
- Start an iOS Simulator and run `flutter run -d <simulator-device-id>`.

## Project structure

```text
lib/
  main.dart                         Firebase initialization and auth gate
  firebase_options.dart             Generated Firebase options for iOS
  pages/                            Login, signup, main, filters, details, guardrails
  models/                           Backend response and upload state models
  services/
    api_config.dart                 FastAPI and tusd address configuration
    auth_service.dart               Firebase authentication and ID tokens
    backend_service.dart            Authenticated FastAPI requests
    upload_service.dart             TUS upload client
    upload_selection_store.dart     Persistent local upload selections
ios/
  Podfile                           iOS 15.0 target and CocoaPods setup
  Runner/GoogleService-Info.plist   Native Firebase iOS configuration
  Runner/Info.plist                 Runner settings and local-network transport policy
```

## Verification

Run static analysis from the project root:

```bash
flutter analyze
```

Static analysis currently passes. There are no valid passing Flutter tests in the repository. `test/widget_test.dart` is the stale generated counter test; it expects the removed counter UI and does not initialize Firebase, so `flutter test` currently fails and should not be cited as a passing verification command.
