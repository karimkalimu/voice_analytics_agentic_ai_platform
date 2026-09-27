import 'package:flutter/material.dart';

class FileFiltersPage extends StatefulWidget {
  const FileFiltersPage({super.key, required this.initialFilters});

  final Map<String, String> initialFilters;

  @override
  State<FileFiltersPage> createState() => _FileFiltersPageState();
}

class _FileFiltersPageState extends State<FileFiltersPage> {
  static const _keys = [
    'created_from',
    'created_to',
    'duration_min',
    'duration_max',
    'taxonomy_label',
    'rms_min',
    'rms_max',
    'noun_count_min',
    'noun_count_max',
    'adjective_count_min',
    'adjective_count_max',
  ];

  late final Map<String, TextEditingController> _fields;
  late String _sentiment;

  @override
  void initState() {
    super.initState();
    _fields = {
      for (final key in _keys)
        key: TextEditingController(text: widget.initialFilters[key] ?? ''),
    };
    _sentiment = widget.initialFilters['sentiment'] ?? '';
  }

  @override
  void dispose() {
    for (final controller in _fields.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Widget _field(String key, String label, {TextInputType? keyboardType}) =>
      TextField(
        controller: _fields[key],
        keyboardType: keyboardType,
        decoration: InputDecoration(labelText: label),
      );

  Widget _range(String label, String minimum, String maximum) => Padding(
    padding: const EdgeInsets.only(top: 16),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: Theme.of(context).textTheme.titleSmall),
        Row(
          children: [
            Expanded(
              child: _field(
                minimum,
                'Min',
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _field(
                maximum,
                'Max',
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
              ),
            ),
          ],
        ),
      ],
    ),
  );

  void _apply() {
    final filters = <String, String>{
      for (final entry in _fields.entries)
        if (entry.value.text.trim().isNotEmpty)
          entry.key: entry.value.text.trim(),
      if (_sentiment.isNotEmpty) 'sentiment': _sentiment,
    };
    Navigator.pop(context, filters);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Filter files')),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Dates use ISO 8601 with a timezone, such as 2026-09-01T00:00:00Z.',
                    ),
                    _field('created_from', 'Created from'),
                    _field('created_to', 'Created to'),
                    _range(
                      'Duration (seconds)',
                      'duration_min',
                      'duration_max',
                    ),
                    const SizedBox(height: 16),
                    _field('taxonomy_label', 'Topic or event label'),
                    const SizedBox(height: 16),
                    DropdownButtonFormField<String>(
                      initialValue: _sentiment,
                      decoration: const InputDecoration(labelText: 'Sentiment'),
                      items: const [
                        DropdownMenuItem(value: '', child: Text('Any')),
                        DropdownMenuItem(
                          value: 'positive',
                          child: Text('Positive'),
                        ),
                        DropdownMenuItem(
                          value: 'neutral',
                          child: Text('Neutral'),
                        ),
                        DropdownMenuItem(
                          value: 'negative',
                          child: Text('Negative'),
                        ),
                      ],
                      onChanged: (value) =>
                          setState(() => _sentiment = value ?? ''),
                    ),
                    _range('Normalized RMS (0–1)', 'rms_min', 'rms_max'),
                    _range('Noun count', 'noun_count_min', 'noun_count_max'),
                    _range(
                      'Adjective count',
                      'adjective_count_min',
                      'adjective_count_max',
                    ),
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  TextButton(
                    onPressed: () => Navigator.pop(context, <String, String>{}),
                    child: const Text('Clear filters'),
                  ),
                  const Spacer(),
                  FilledButton(onPressed: _apply, child: const Text('Apply')),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
