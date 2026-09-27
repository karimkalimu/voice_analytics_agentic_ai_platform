import 'package:flutter/material.dart';

import '../models/guardrails_info.dart';

class GuardrailsPage extends StatelessWidget {
  const GuardrailsPage({super.key, required this.guardrails});

  final GuardrailsInfo guardrails;

  String _number(double value) =>
      value == value.roundToDouble() ? value.toInt().toString() : '$value';

  Widget _limit(String label, String value) => Padding(
    padding: const EdgeInsets.only(bottom: 6),
    child: Text('$label: $value'),
  );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Guardrails')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('POC limits', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          _limit(
            'Maximum audio duration',
            '${_number(guardrails.maxAudioDurationSec)} seconds',
          ),
          _limit(
            'Maximum file size',
            '${_number(guardrails.maxAudioSizeMb)} MB',
          ),
          _limit('Maximum active files', '${guardrails.maxActiveFiles}'),
          _limit('Minimum normalized RMS', _number(guardrails.minAudioRms)),
          _limit(
            'Minimum transcript words',
            '${guardrails.minTranscriptWords}',
          ),
          _limit(
            'Minimum words per minute',
            _number(guardrails.minTranscriptWordsPerMinute),
          ),
          _limit(
            'Minimum average word confidence',
            _number(guardrails.minAverageWordConfidence),
          ),
          const Divider(height: 24),
          for (final section in guardrails.sections) ...[
            Text(section.title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            for (final item in section.items)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text('• $item'),
              ),
            const SizedBox(height: 12),
          ],
        ],
      ),
    );
  }
}
