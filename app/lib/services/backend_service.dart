import 'dart:convert';
import 'dart:io';

import '../models/uploaded_file.dart';
import '../models/guardrails_info.dart';
import 'api_config.dart';
import 'auth_service.dart';

class BackendService {
  static Future<({int status, String body})> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final credentials = await AuthService.credentials();
    final client = HttpClient();
    try {
      final request = await client.openUrl(
        method,
        Uri.parse('${ApiConfig.fastApiBaseUrl}$path'),
      );
      request.headers.set(
        HttpHeaders.authorizationHeader,
        'Bearer ${credentials.token}',
      );
      if (body != null) {
        request.headers.contentType = ContentType.json;
        request.write(jsonEncode(body));
      }
      final response = await request.close();
      return (
        status: response.statusCode,
        body: await utf8.decoder.bind(response).join(),
      );
    } on SocketException {
      throw const HttpException('Could not connect to backend.');
    } finally {
      client.close();
    }
  }

  static void _expectStatus(
    ({int status, String body}) response,
    int expected,
  ) {
    if (response.status == expected) return;
    if (response.status >= HttpStatus.internalServerError) {
      throw const HttpException('Server error. Please try again.');
    }
    var detail = response.body;
    try {
      final value =
          (jsonDecode(response.body) as Map<String, dynamic>)['detail'];
      if (value is List) {
        final messages = value
            .whereType<Map>()
            .map((item) {
              final location = item['loc'];
              final field = location is List && location.isNotEmpty
                  ? '${location.last}: '
                  : '';
              return '$field${item['msg']}';
            })
            .join('; ');
        detail = messages.isEmpty ? response.body : messages;
      } else {
        detail = value?.toString() ?? response.body;
      }
    } catch (_) {}
    throw HttpException('${response.status}: $detail');
  }

  static Future<List<UploadedFile>> getFiles({
    Map<String, String> filters = const {},
  }) async {
    final path = Uri(
      path: '/files',
      queryParameters: filters.isEmpty ? null : filters,
    );
    final response = await _request('GET', path.toString());
    _expectStatus(response, HttpStatus.ok);
    return (jsonDecode(response.body) as List)
        .map((item) => UploadedFile.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  static Future<GuardrailsInfo> getGuardrails() async {
    final response = await _request('GET', '/guardrails');
    _expectStatus(response, HttpStatus.ok);
    return GuardrailsInfo.fromJson(
      jsonDecode(response.body) as Map<String, dynamic>,
    );
  }

  static Future<UploadedFile> getFile(int id) async {
    final response = await _request('GET', '/files/$id');
    _expectStatus(response, HttpStatus.ok);
    return UploadedFile.fromJson(
      jsonDecode(response.body) as Map<String, dynamic>,
    );
  }

  static Future<({int status, UploadedFile file})> addLayer2(
    int id,
    List<String> options, {
    bool uniqueNouns = false,
    String topic = '',
  }) async {
    final body = <String, dynamic>{'options': options};
    final config = {
      if (options.contains('count_nouns'))
        'count_nouns': {'unique_only': uniqueNouns},
      if (options.contains('topic_mentions'))
        'topic_mentions': {'topic': topic.trim()},
    };
    if (config.isNotEmpty) body['config'] = config;
    final response = await _request('POST', '/files/$id/layer2', body: body);
    if (response.status != HttpStatus.ok &&
        response.status != HttpStatus.accepted) {
      _expectStatus(response, HttpStatus.ok);
    }
    return (
      status: response.status,
      file: UploadedFile.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      ),
    );
  }

  static Future<String> getTranscript(int id) async {
    final response = await _request('GET', '/files/$id/transcript');
    _expectStatus(response, HttpStatus.ok);
    return (jsonDecode(response.body) as Map<String, dynamic>)['transcript']
        as String;
  }

  static Future<void> deleteFile(int id) async {
    final response = await _request('DELETE', '/files/$id');
    _expectStatus(response, HttpStatus.noContent);
  }
}
