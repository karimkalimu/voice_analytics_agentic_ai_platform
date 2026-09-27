import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:file_picker/file_picker.dart';
import 'package:path_provider/path_provider.dart';

import '../models/upload_selection.dart';

class UploadSelectionStore {
  static String _safeUserId(String userId) =>
      base64Url.encode(utf8.encode(userId)).replaceAll('=', '');

  static String _newId() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    return base64Url.encode(bytes).replaceAll('=', '');
  }

  static Future<Directory> _userDirectory(String userId) async {
    final support = await getApplicationSupportDirectory();
    return Directory(
      '${support.path}/upload-selections/${_safeUserId(userId)}',
    );
  }

  static Future<UploadSelection> create(
    PlatformFile file, {
    required String userId,
    required Set<String> layer2Options,
    required bool uniqueNouns,
    required String topic,
  }) async {
    final userDirectory = await _userDirectory(userId);
    await userDirectory.create(recursive: true);
    late String id;
    late Directory directory;
    do {
      id = _newId();
      directory = Directory('${userDirectory.path}/$id');
    } while (await directory.exists());
    await directory.create(recursive: true);
    final localPath = '${directory.path}/audio';
    try {
      await file.xFile.saveTo(localPath);
      final selection = UploadSelection(
        id: id,
        userId: userId,
        originalName: file.name,
        localPath: localPath,
        layer2Options: layer2Options.toList(),
        uniqueNouns: uniqueNouns,
        topic: topic,
        createdAt: DateTime.now().microsecondsSinceEpoch,
      );
      await File(
        '${directory.path}/selection.json',
      ).writeAsString(jsonEncode(selection.toJson()), flush: true);
      return selection;
    } catch (_) {
      if (await directory.exists()) await directory.delete(recursive: true);
      rethrow;
    }
  }

  static Future<List<UploadSelection>> pending(String userId) async {
    final directory = await _userDirectory(userId);
    if (!await directory.exists()) return [];
    final selections = <UploadSelection>[];
    await for (final entity in directory.list()) {
      if (entity is! Directory) continue;
      try {
        final selection = UploadSelection.fromJson(
          jsonDecode(await File('${entity.path}/selection.json').readAsString())
              as Map<String, dynamic>,
        );
        if (selection.userId == userId &&
            await File(selection.localPath).exists()) {
          selections.add(selection);
        }
      } catch (_) {}
    }
    selections.sort((a, b) => a.createdAt.compareTo(b.createdAt));
    return selections;
  }

  static Future<void> remove(UploadSelection selection) async {
    final directory = File(selection.localPath).parent;
    final metadata = File('${directory.path}/selection.json');
    if (await metadata.exists()) await metadata.delete();
    try {
      if (await directory.exists()) await directory.delete(recursive: true);
    } catch (_) {}
  }
}
