import 'dart:async';

import 'package:flutter/material.dart';

import '../models/file_status.dart';
import '../models/uploaded_file.dart';
import '../services/backend_service.dart';

class FileDetailsPage extends StatefulWidget {
  const FileDetailsPage({super.key, required this.fileId});

  final int fileId;

  @override
  State<FileDetailsPage> createState() => _FileDetailsPageState();
}

class _FileDetailsPageState extends State<FileDetailsPage> {
  static const _layer2Labels = {
    'rms': 'RMS audio level',
    'count_nouns': 'Noun count',
    'count_adjectives': 'Adjective count',
    'sentiment': 'Sentiment',
    'topic_mentions': 'Topic mentions',
  };

  UploadedFile? _file;
  String? _transcript;
  bool _loading = true;
  bool _loadingTranscript = false;
  bool _deleting = false;
  bool _addingLayer2 = false;
  bool _uniqueNouns = false;
  int _fileRequest = 0;
  Timer? _pollTimer;
  final Set<String> _newOptions = {};
  final TextEditingController _topicController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _loadFile();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _topicController.dispose();
    super.dispose();
  }

  void _showError(Object error) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(error.toString()),
        duration: const Duration(seconds: 8),
      ),
    );
  }

  void _schedulePoll() {
    _pollTimer?.cancel();
    if (!mounted || !isActiveFileStatus(_file?.status ?? '')) return;
    _pollTimer = Timer(
      const Duration(seconds: 2),
      () => _loadFile(polling: true),
    );
  }

  Future<void> _loadFile({bool polling = false}) async {
    _pollTimer?.cancel();
    final request = ++_fileRequest;
    if (!polling) setState(() => _loading = true);
    try {
      final file = await BackendService.getFile(widget.fileId);
      if (mounted && request == _fileRequest) {
        setState(() {
          _file = file;
          _newOptions.removeAll(file.layer2Options);
        });
      }
    } catch (error) {
      if (mounted && request == _fileRequest && !polling) _showError(error);
    } finally {
      if (mounted && request == _fileRequest) {
        if (!polling) setState(() => _loading = false);
        _schedulePoll();
      }
    }
  }

  Future<void> _addLayer2() async {
    final file = _file;
    if (file == null || file.status == 'rejected') return;
    final options = _layer2Labels.keys
        .where(
          (option) =>
              _newOptions.contains(option) &&
              !file.layer2Options.contains(option),
        )
        .toList();
    if (options.isEmpty) return;
    final topic = _topicController.text.trim();
    if (options.contains('topic_mentions') &&
        (topic.isEmpty || topic.runes.length > 100)) {
      _showError('Enter a topic of 1–100 characters.');
      return;
    }
    setState(() => _addingLayer2 = true);
    try {
      final result = await BackendService.addLayer2(
        widget.fileId,
        options,
        uniqueNouns: _uniqueNouns,
        topic: topic,
      );
      if (mounted) {
        setState(() {
          _file = result.file;
          _newOptions.clear();
          _uniqueNouns = false;
          _topicController.clear();
        });
        if (result.status == 202) _schedulePoll();
      }
    } catch (error) {
      if (mounted) _showError(error);
    } finally {
      if (mounted) setState(() => _addingLayer2 = false);
    }
  }

  Future<void> _loadTranscript() async {
    if (_file?.transcriptAvailable != true) return;
    setState(() => _loadingTranscript = true);
    try {
      final transcript = await BackendService.getTranscript(widget.fileId);
      if (mounted) setState(() => _transcript = transcript);
    } catch (error) {
      if (mounted) _showError(error);
    } finally {
      if (mounted) setState(() => _loadingTranscript = false);
    }
  }

  Future<void> _deleteFile() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete file?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _deleting = true);
    try {
      await BackendService.deleteFile(widget.fileId);
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) _showError(error);
    } finally {
      if (mounted) setState(() => _deleting = false);
    }
  }

  Widget _field(String label, Object? value) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Text('$label: ${value ?? 'None'}'),
  );

  String _items(List<String> items, String emptyText) =>
      items.isEmpty ? emptyText : items.join(', ');

  Object? _result(UploadedFile file, String option, String key) {
    final result = file.layer2Results[option];
    return result is Map ? result[key] : null;
  }

  @override
  Widget build(BuildContext context) {
    final file = _file;
    final rms = file == null ? null : _result(file, 'rms', 'rms_normalized');
    final nouns = file == null ? null : _result(file, 'count_nouns', 'count');
    final adjectives = file == null
        ? null
        : _result(file, 'count_adjectives', 'count');
    final sentiment = file == null ? null : _result(file, 'sentiment', 'label');
    final mentions = file == null
        ? null
        : _result(file, 'topic_mentions', 'count');
    return Scaffold(
      appBar: AppBar(
        title: Text(file?.originalName ?? 'File details'),
        actions: [
          IconButton(
            onPressed: _loading || _addingLayer2 ? null : _loadFile,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: _loading && file == null
          ? const Center(child: CircularProgressIndicator())
          : file == null
          ? Center(
              child: TextButton(
                onPressed: _loadFile,
                child: const Text('Retry loading file'),
              ),
            )
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _field('ID', file.id),
                  _field('User ID', file.userId),
                  _field('Upload ID', file.uploadId),
                  _field('Name', file.originalName),
                  _field('Status', switch (file.status) {
                    'validating_audio' => 'Validating audio',
                    'validating_transcript' => 'Validating transcript',
                    'analyzing_layer2' => 'Layer 2 analysis in progress',
                    'layer2_failed' => 'Layer 2 analysis failed',
                    'rejected' => 'Rejected',
                    _ => file.status,
                  }),
                  _field('Created', file.createdAt),
                  const Divider(height: 24),
                  if (file.language != null) _field('Language', file.language),
                  if (file.error?.trim().isNotEmpty ?? false)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(
                        '${file.status == 'rejected' ? 'Rejection' : 'Processing error'}: ${file.error!.trim()}',
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ),
                  if (file.durationSec != null)
                    _field(
                      'Duration',
                      '${file.durationSec!.toStringAsFixed(1)} s',
                    ),
                  if (file.summary != null) _field('Summary', file.summary),
                  _field(
                    'Professional topics',
                    _items(
                      file.professionalTopics,
                      'No professional topics detected',
                    ),
                  ),
                  _field(
                    'Personal topics',
                    _items(file.personalTopics, 'No personal topics detected'),
                  ),
                  _field(
                    'Upcoming events',
                    _items(file.upcomingEvents, 'No upcoming events detected'),
                  ),
                  const Divider(height: 24),
                  if (file.layer2Options.contains('rms') && rms is num)
                    _field('Normalized RMS', rms),
                  if (file.layer2Options.contains('count_nouns') &&
                      nouns is int)
                    _field('Noun count', nouns),
                  if (file.layer2Options.contains('count_nouns'))
                    _field(
                      'Noun counting',
                      (file.layer2Config['count_nouns']
                                  as Map?)?['unique_only'] ==
                              true
                          ? 'Unique nouns only'
                          : 'All noun occurrences',
                    ),
                  if (file.layer2Options.contains('count_adjectives') &&
                      adjectives is int)
                    _field('Adjective count', adjectives),
                  if (file.layer2Options.contains('sentiment') &&
                      sentiment is String)
                    _field('Sentiment', sentiment),
                  if (file.layer2Options.contains('topic_mentions'))
                    _field(
                      'Topic',
                      (file.layer2Config['topic_mentions'] as Map?)?['topic'],
                    ),
                  if (file.layer2Options.contains('topic_mentions') &&
                      mentions is num)
                    _field('Mentions', mentions),
                  if (file.audioSha256 != null)
                    _field('Audio SHA-256', file.audioSha256),
                  if (file.transcriptionVersion != null)
                    _field('Transcription version', file.transcriptionVersion),
                  if (file.analysisVersion != null)
                    _field('Analysis version', file.analysisVersion),
                  if (file.guardrailVersion != null)
                    _field('Guardrail version', file.guardrailVersion),
                  if (isActiveFileStatus(file.status))
                    Padding(
                      padding: EdgeInsets.only(bottom: 8),
                      child: Row(
                        children: [
                          const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          ),
                          const SizedBox(width: 8),
                          Text(switch (file.status) {
                            'uploaded' => 'Preparing processing',
                            'validating_audio' => 'Validating audio',
                            'transcribing' => 'Transcription in progress',
                            'validating_transcript' => 'Validating transcript',
                            'transcribed' => 'Preparing analysis',
                            'analyzing' => 'Analysis in progress',
                            _ => 'Layer 2 analysis in progress',
                          }),
                        ],
                      ),
                    ),
                  if ((file.status == 'completed' ||
                          file.status == 'layer2_failed') &&
                      _layer2Labels.keys.any(
                        (option) => !file.layer2Options.contains(option),
                      )) ...[
                    const Divider(height: 24),
                    Text(
                      'Add Layer 2 analyses',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const Text('Already added options are checked.'),
                    Wrap(
                      spacing: 8,
                      children: [
                        for (final option in _layer2Labels.entries)
                          FilterChip(
                            label: Text(option.value),
                            selected:
                                file.layer2Options.contains(option.key) ||
                                _newOptions.contains(option.key),
                            onSelected:
                                _addingLayer2 ||
                                    file.layer2Options.contains(option.key)
                                ? null
                                : (selected) => setState(() {
                                    if (selected) {
                                      _newOptions.add(option.key);
                                    } else {
                                      _newOptions.remove(option.key);
                                      if (option.key == 'count_nouns') {
                                        _uniqueNouns = false;
                                      }
                                    }
                                  }),
                          ),
                      ],
                    ),
                    if (_newOptions.contains('count_nouns'))
                      CheckboxListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Count unique nouns only'),
                        value: _uniqueNouns,
                        onChanged: _addingLayer2
                            ? null
                            : (value) =>
                                  setState(() => _uniqueNouns = value ?? false),
                      ),
                    if (_newOptions.contains('topic_mentions'))
                      TextField(
                        controller: _topicController,
                        enabled: !_addingLayer2,
                        decoration: const InputDecoration(
                          labelText: 'Topic',
                          helperText: 'Required, 1–100 characters',
                        ),
                      ),
                    FilledButton(
                      onPressed:
                          _loading || _addingLayer2 || _newOptions.isEmpty
                          ? null
                          : _addLayer2,
                      child: const Text('Add analyses'),
                    ),
                  ],
                  _field('Transcript available', file.transcriptAvailable),
                  if (file.transcriptAvailable)
                    OutlinedButton.icon(
                      onPressed: _loadingTranscript ? null : _loadTranscript,
                      icon: const Icon(Icons.description_outlined),
                      label: const Text('View transcript'),
                    ),
                  if (_loadingTranscript) const CircularProgressIndicator(),
                  if (_transcript != null) SelectableText(_transcript!),
                  const Divider(height: 24),
                  TextButton.icon(
                    onPressed: _deleting || _addingLayer2 ? null : _deleteFile,
                    icon: const Icon(Icons.delete_outline),
                    label: const Text('Delete file'),
                    style: TextButton.styleFrom(
                      foregroundColor: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ],
              ),
            ),
    );
  }
}
