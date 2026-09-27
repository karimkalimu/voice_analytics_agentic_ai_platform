import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:tusc/tusc.dart';

import '../models/upload_selection.dart';
import 'api_config.dart';
import 'auth_service.dart';

class _SelectionTusClient extends TusStreamClient {
  _SelectionTusClient({
    required this.resumeIdentity,
    required super.fileStreamGenerator,
    required super.fileSize,
    required super.fileName,
    required super.url,
    required super.cache,
    required super.headers,
    required super.metadata,
  });

  final String resumeIdentity;

  @override
  String generateFingerprint() => resumeIdentity;
}

class UploadService {
  static Future<void> upload(
    UploadSelection selection, {
    required void Function(double) onProgress,
  }) async {
    final credentials = await AuthService.credentials();
    if (credentials.uid != selection.userId) {
      throw StateError('Upload belongs to another user.');
    }
    final directory = await getApplicationSupportDirectory();
    final file = File(selection.localPath);
    final cache = TusPersistentCache(directory.path);
    final resumeIdentity = [
      ApiConfig.tusdBaseUrl,
      credentials.uid,
      selection.id,
    ].join('|');
    final client = _SelectionTusClient(
      resumeIdentity: resumeIdentity,
      url: '${ApiConfig.tusdBaseUrl}/files/',
      fileStreamGenerator: file.openRead,
      fileSize: await file.length(),
      fileName: selection.originalName,
      cache: cache,
      headers: {'Authorization': 'Bearer ${credentials.token}'},
      metadata: {
        'user_id': credentials.uid,
        'filename': selection.originalName,
        if (selection.layer2Options.isNotEmpty)
          'layer2_options': jsonEncode(selection.layer2Options),
        if (selection.layer2Options.contains('count_nouns') ||
            selection.layer2Options.contains('topic_mentions'))
          'layer2_config': jsonEncode({
            if (selection.layer2Options.contains('count_nouns'))
              'count_nouns': {'unique_only': selection.uniqueNouns},
            if (selection.layer2Options.contains('topic_mentions'))
              'topic_mentions': {'topic': selection.topic},
          }),
      },
    );

    try {
      await client.startUpload(
        onProgress: (sent, total, _) {
          onProgress(total == 0 ? 1 : sent / total);
        },
      );
      await cache.remove(resumeIdentity);
    } finally {
      client.close();
    }
  }
}
