# Flutter iOS client

[Project overview](../README.md) · [Backend setup](../backend/README.md)

The minimal Flutter UI supports Firebase signup/login, one or many resumable uploads, Layer 2 selection, processing status, filters, transcripts, analysis results, guardrails, retry, and deletion.

## Requirements

- Flutter 3.41.9 with Dart 3.11.5 compatible tooling
- macOS, Xcode, CocoaPods, and an iOS 15+ Simulator
- A Firebase iOS app with Email/Password authentication enabled

## Firebase configuration

The Firebase project must match the Runner bundle ID `com.example.voiceAnalyticsAgenticAiPlatform`.

Required client files:

```text
ios/Runner/GoogleService-Info.plist
lib/firebase_options.dart
```

To use another Firebase project, replace the plist and regenerate the Dart options:

```sh
dart pub global activate flutterfire_cli
flutterfire configure --platforms=ios
```

Update the Runner bundle identifier too if the new Firebase app uses a different value.

## Backend address

The default FastAPI and tusd hosts are configured in `lib/services/api_config.dart` and use `localhost` ports `8000` and `8081`.

For another host using the same HTTP ports:

```sh
flutter run -d <simulator-device-id> --dart-define=BACKEND_HOST=<hostname-or-ip>
```

Use HTTPS and update the absolute URLs in `api_config.dart` when deploying behind TLS or using different ports.

## Run

Start the backend first, then:

```sh
flutter pub get
flutter devices
flutter run -d <simulator-device-id>
```

## Client flow

- Firebase ID tokens authenticate FastAPI requests and TUS upload creation.
- Every selected file has its own persisted resume identity, progress, and retry state.
- Optional Layer 2 choices are `rms`, `count_nouns`, `count_adjectives`, `sentiment`, and `topic_mentions`.
- File results include status, transcript, duration, summary, taxonomy, Layer 2 output, and safe errors.
- Filters are sent to the backend; guardrail limits are loaded from `GET /guardrails`.

## Verification

```sh
flutter analyze
```

Static analysis passes. No automated Flutter UI test suite is provided for this POC. The complete simulator flow has been tested manually, including authentication, multiple uploads, processing, results, filtering, guardrails, retry, and deletion.
