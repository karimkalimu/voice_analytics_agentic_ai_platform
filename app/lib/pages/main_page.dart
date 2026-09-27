import 'dart:async';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../models/file_status.dart';
import '../models/guardrails_info.dart';
import '../models/upload_selection.dart';
import '../models/uploaded_file.dart';
import '../services/auth_service.dart';
import '../services/backend_service.dart';
import '../services/upload_selection_store.dart';
import '../services/upload_service.dart';
import 'file_details_page.dart';
import 'file_filters_page.dart';
import 'guardrails_page.dart';

class _UploadRow {
  _UploadRow(this.selection, this.status);

  final UploadSelection selection;
  String status;
  double? progress;

  bool get failed => status.startsWith('Failed');
}

class MainPage extends StatefulWidget {
  const MainPage({super.key});

  @override
  State<MainPage> createState() => _MainPageState();
}

class _MainPageState extends State<MainPage> {
  static const _layer2Labels = {
    'rms': 'RMS',
    'count_nouns': 'Nouns',
    'count_adjectives': 'Adjectives',
    'sentiment': 'Sentiment',
    'topic_mentions': 'Topic mentions',
  };

  bool _uploading = false;
  bool _refreshing = false;
  bool _hasOutstandingProcessing = false;
  int _refreshRequest = 0;
  bool _uniqueNouns = false;
  List<_UploadRow> _uploads = [];
  List<UploadedFile>? _files;
  GuardrailsInfo? _guardrails;
  Timer? _pollTimer;
  final Set<String> _layer2Options = {};
  final TextEditingController _topicController = TextEditingController();
  Map<String, String> _filters = {};

  @override
  void initState() {
    super.initState();
    _uploading = true;
    _refreshFiles();
    _loadGuardrails();
    _restoreUploads();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _topicController.dispose();
    super.dispose();
  }

  void _schedulePoll() {
    _pollTimer?.cancel();
    if (!mounted || !_hasOutstandingProcessing) return;
    _pollTimer = Timer(
      const Duration(seconds: 2),
      () => _refreshFiles(polling: true),
    );
  }

  Future<void> _refreshFiles({bool polling = false}) async {
    if (!mounted) return;
    _pollTimer?.cancel();
    final request = ++_refreshRequest;
    if (!polling) setState(() => _refreshing = true);
    try {
      final filters = Map<String, String>.from(_filters);
      final files = await BackendService.getFiles(filters: filters);
      var hasOutstanding = files.any((file) => isActiveFileStatus(file.status));
      if (!hasOutstanding && filters.isNotEmpty && _hasOutstandingProcessing) {
        final allFiles = await BackendService.getFiles();
        hasOutstanding = allFiles.any(
          (file) => isActiveFileStatus(file.status),
        );
      }
      if (mounted && request == _refreshRequest) {
        setState(() {
          _files = files;
          _hasOutstandingProcessing = hasOutstanding;
        });
      }
    } catch (error) {
      if (mounted && request == _refreshRequest && !polling) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(error.toString()),
            duration: const Duration(seconds: 8),
          ),
        );
      }
    } finally {
      if (mounted && request == _refreshRequest) {
        setState(() => _refreshing = false);
        _schedulePoll();
      }
    }
  }

  Future<GuardrailsInfo?> _loadGuardrails() async {
    try {
      final guardrails = await BackendService.getGuardrails();
      if (mounted) setState(() => _guardrails = guardrails);
      return guardrails;
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(error.toString())));
      }
      return null;
    }
  }

  Future<void> _openGuardrails() async {
    final guardrails = _guardrails ?? await _loadGuardrails();
    if (guardrails == null || !mounted) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(builder: (_) => GuardrailsPage(guardrails: guardrails)),
    );
  }

  Future<void> _openFile(UploadedFile file) async {
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => FileDetailsPage(fileId: file.id)),
    );
    if (mounted) await _refreshFiles();
  }

  Future<void> _openFilters() async {
    final filters = await Navigator.of(context).push<Map<String, String>>(
      MaterialPageRoute(
        builder: (_) => FileFiltersPage(initialFilters: _filters),
      ),
    );
    if (filters == null || !mounted) return;
    setState(() {
      _filters = filters;
      _files = null;
    });
    await _refreshFiles();
  }

  String _statusText(UploadedFile file) => switch (file.status) {
    'uploaded' => 'Uploaded',
    'validating_audio' => 'Validating audio',
    'transcribing' => 'Transcription in progress',
    'validating_transcript' => 'Validating transcript',
    'transcribed' => 'Transcription completed',
    'analyzing' => 'Analysis in progress',
    'analyzing_layer2' => 'Layer 2 analysis in progress',
    'completed' => 'Analysis completed',
    'analysis_failed' => 'Analysis failed',
    'layer2_failed' => 'Layer 2 analysis failed',
    'unsupported_language' => 'Unsupported language',
    'transcription_failed' => 'Transcription failed',
    'rejected' => 'Rejected',
    _ => file.status,
  };

  String _number(double value) =>
      value == value.roundToDouble() ? value.toInt().toString() : '$value';

  String? _guardrailsHint() {
    final guardrails = _guardrails;
    if (guardrails == null) return null;
    final items = guardrails.sections.expand((section) => section.items);
    final language = items.cast<String?>().firstWhere(
      (item) => item!.toLowerCase().contains('english'),
      orElse: () => null,
    );
    final profanity = items.cast<String?>().firstWhere(
      (item) => item!.toLowerCase().contains('profanity'),
      orElse: () => null,
    );
    return [
      if (language != null) language.replaceAll(RegExp(r'\.$'), ''),
      'Up to ${_number(guardrails.maxAudioDurationSec)} sec',
      'Up to ${_number(guardrails.maxAudioSizeMb)} MB',
      if (profanity != null) profanity.replaceAll(RegExp(r'\.$'), ''),
    ].join(' • ');
  }

  String _items(List<String> items, String emptyText) =>
      items.isEmpty ? emptyText : items.join(', ');

  void _setUpload(_UploadRow upload, String status, [double? progress]) {
    if (!mounted) return;
    setState(() {
      upload.status = status;
      upload.progress = progress;
    });
  }

  Future<void> _restoreUploads() async {
    try {
      final credentials = await AuthService.credentials();
      final selections = await UploadSelectionStore.pending(credentials.uid);
      if (!mounted || selections.isEmpty) return;
      final uploads = [
        for (final selection in selections)
          _UploadRow(selection, 'Queued to resume'),
      ];
      setState(() {
        _uploading = true;
        _uploads = uploads;
      });
      await _processUploads(uploads);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(error.toString())));
      }
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  Future<void> _processUploads(List<_UploadRow> uploads) async {
    for (final upload in uploads) {
      _setUpload(upload, 'Uploading 0%', 0);
      try {
        await UploadService.upload(
          upload.selection,
          onProgress: (progress) => _setUpload(
            upload,
            'Uploading ${(progress * 100).round()}%',
            progress,
          ),
        );
        await UploadSelectionStore.remove(upload.selection);
        _setUpload(upload, 'Uploaded');
        if (mounted) {
          setState(() => _hasOutstandingProcessing = true);
        }
        await _refreshFiles();
      } catch (error) {
        _setUpload(upload, 'Failed. Tap retry to resume.');
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                'Upload failed for ${upload.selection.originalName}: $error',
              ),
            ),
          );
        }
      }
    }
  }

  Future<void> _retryUpload(_UploadRow upload) async {
    setState(() => _uploading = true);
    try {
      await _processUploads([upload]);
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  Future<void> _upload() async {
    final topic = _topicController.text.trim();
    if (_layer2Options.contains('topic_mentions') &&
        (topic.isEmpty || topic.runes.length > 100)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Enter a topic of 1–100 characters.')),
      );
      return;
    }
    setState(() => _uploading = true);

    try {
      final files = await FilePicker.pickFiles(type: FileType.audio);
      if (!mounted || files.isEmpty) return;
      final options = _layer2Options.toSet();
      final uniqueNouns = _uniqueNouns;
      final credentials = await AuthService.credentials();
      final uploads = <_UploadRow>[];
      for (final file in files) {
        try {
          final selection = await UploadSelectionStore.create(
            file,
            userId: credentials.uid,
            layer2Options: options,
            uniqueNouns: uniqueNouns,
            topic: topic,
          );
          uploads.add(_UploadRow(selection, 'Queued'));
        } catch (_) {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('Could not prepare ${file.name}.')),
            );
          }
        }
      }
      if (!mounted || uploads.isEmpty) return;
      setState(() {
        _uploads = [..._uploads.where((upload) => upload.failed), ...uploads];
      });
      await _processUploads(uploads);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not select audio files.')),
        );
      }
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  Future<void> _logout(BuildContext context) async {
    try {
      await AuthService.logout();
    } on FirebaseAuthException catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(error.message ?? error.code)));
      }
    }
  }

  Future<void> _confirmLogout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Log out?'),
        content: const Text('You will return to the login screen.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Log out'),
          ),
        ],
      ),
    );
    if (confirmed == true && mounted) await _logout(context);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Audio files'),
        actions: [
          IconButton(
            onPressed: _openGuardrails,
            icon: const Icon(Icons.shield_outlined),
            tooltip: 'Guardrails',
          ),
          IconButton(
            onPressed: _confirmLogout,
            icon: const Icon(Icons.logout),
            tooltip: 'Log out',
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Optional analyses',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 4),
                const Text(
                  'RMS checks audio level; counts, sentiment, and topic mentions use the transcript. Leave all unselected for standard analysis.',
                ),
                if (_guardrailsHint() case final hint?) ...[
                  const SizedBox(height: 8),
                  Text(hint),
                ],
                const SizedBox(height: 8),
                Wrap(
                  spacing: 4,
                  runSpacing: 4,
                  children: [
                    for (final option in _layer2Labels.entries)
                      FilterChip(
                        label: Text(option.value),
                        selected: _layer2Options.contains(option.key),
                        showCheckmark: false,
                        selectedColor: Theme.of(
                          context,
                        ).colorScheme.primaryContainer,
                        visualDensity: VisualDensity.compact,
                        materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        labelPadding: const EdgeInsets.symmetric(horizontal: 2),
                        padding: const EdgeInsets.symmetric(horizontal: 4),
                        onSelected: _uploading
                            ? null
                            : (selected) => setState(() {
                                if (selected) {
                                  _layer2Options.add(option.key);
                                } else {
                                  _layer2Options.remove(option.key);
                                  if (option.key == 'count_nouns') {
                                    _uniqueNouns = false;
                                  }
                                }
                              }),
                      ),
                  ],
                ),
                if (_layer2Options.contains('count_nouns'))
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Count unique nouns only'),
                    value: _uniqueNouns,
                    onChanged: _uploading
                        ? null
                        : (value) =>
                              setState(() => _uniqueNouns = value ?? false),
                  ),
                if (_layer2Options.contains('topic_mentions'))
                  TextField(
                    controller: _topicController,
                    enabled: !_uploading,
                    decoration: const InputDecoration(
                      labelText: 'Topic',
                      helperText: 'Required, 1–100 characters',
                    ),
                  ),
                const SizedBox(height: 8),
                FilledButton.icon(
                  onPressed: _uploading ? null : _upload,
                  icon: const Icon(Icons.audio_file),
                  label: const Text('Upload audio files'),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          if (_uploads.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'Uploads',
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
            ),
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 144),
              child: ListView.builder(
                shrinkWrap: true,
                itemCount: _uploads.length,
                itemBuilder: (context, index) {
                  final upload = _uploads[index];
                  return Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 4,
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(upload.selection.originalName),
                        Text(upload.status),
                        if (upload.progress != null)
                          LinearProgressIndicator(value: upload.progress),
                        if (upload.failed)
                          TextButton(
                            onPressed: _uploading
                                ? null
                                : () => _retryUpload(upload),
                            child: const Text('Retry'),
                          ),
                      ],
                    ),
                  );
                },
              ),
            ),
            const Divider(height: 1),
          ],
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    'Your files',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                TextButton.icon(
                  onPressed: _openFilters,
                  icon: const Icon(Icons.filter_list),
                  label: Text(
                    _filters.isEmpty
                        ? 'Filters'
                        : 'Filters (${_filters.length})',
                  ),
                ),
                IconButton(
                  onPressed: _refreshing ? null : _refreshFiles,
                  icon: const Icon(Icons.refresh),
                  tooltip: 'Refresh files',
                ),
              ],
            ),
          ),
          if (_refreshing) const LinearProgressIndicator(),
          Expanded(
            child: _files == null
                ? Center(
                    child: Text(
                      _refreshing
                          ? 'Loading files...'
                          : 'Unable to load files.',
                    ),
                  )
                : _files!.isEmpty
                ? Center(
                    child: Text(
                      _filters.isEmpty
                          ? 'No files yet.'
                          : 'No files match these filters.',
                    ),
                  )
                : ListView.separated(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    itemCount: _files!.length,
                    separatorBuilder: (_, _) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final file = _files![index];
                      return ListTile(
                        onTap: () => _openFile(file),
                        title: Text(file.originalName),
                        subtitle: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(_statusText(file)),
                            if (file.durationSec != null)
                              Text(
                                'Duration: ${file.durationSec!.toStringAsFixed(1)} s',
                              ),
                            if (file.error?.trim().isNotEmpty ?? false)
                              Text(
                                file.error!.trim(),
                                style: TextStyle(
                                  color: Theme.of(context).colorScheme.error,
                                ),
                              ),
                            if (file.status == 'completed' ||
                                file.status == 'analyzing_layer2' ||
                                file.status == 'layer2_failed') ...[
                              Text(
                                'Summary: ${file.summary ?? 'Not available.'}',
                              ),
                              Text(
                                'Professional topics: ${_items(file.professionalTopics, 'No professional topics detected')}',
                              ),
                              Text(
                                'Personal topics: ${_items(file.personalTopics, 'No personal topics detected')}',
                              ),
                              Text(
                                'Upcoming events: ${_items(file.upcomingEvents, 'No upcoming events detected')}',
                              ),
                            ],
                          ],
                        ),
                        trailing:
                            file.status == 'validating_audio' ||
                                file.status == 'transcribing' ||
                                file.status == 'validating_transcript' ||
                                file.status == 'analyzing' ||
                                file.status == 'analyzing_layer2'
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : file.status == 'completed'
                            ? const Icon(Icons.check_circle)
                            : null,
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
