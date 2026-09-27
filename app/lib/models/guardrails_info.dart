class GuardrailsInfo {
  const GuardrailsInfo({
    required this.maxAudioDurationSec,
    required this.maxAudioSizeMb,
    required this.maxActiveFiles,
    required this.minAudioRms,
    required this.minTranscriptWords,
    required this.minTranscriptWordsPerMinute,
    required this.minAverageWordConfidence,
    required this.sections,
  });

  final double maxAudioDurationSec;
  final double maxAudioSizeMb;
  final int maxActiveFiles;
  final double minAudioRms;
  final int minTranscriptWords;
  final double minTranscriptWordsPerMinute;
  final double minAverageWordConfidence;
  final List<GuardrailSection> sections;

  factory GuardrailsInfo.fromJson(Map<String, dynamic> json) {
    final limits = json['limits'] as Map<String, dynamic>;
    return GuardrailsInfo(
      maxAudioDurationSec: (limits['max_audio_duration_sec'] as num).toDouble(),
      maxAudioSizeMb: (limits['max_audio_size_mb'] as num).toDouble(),
      maxActiveFiles: (limits['max_active_files_per_user'] as num).toInt(),
      minAudioRms: (limits['min_audio_rms'] as num).toDouble(),
      minTranscriptWords: (limits['min_transcript_words'] as num).toInt(),
      minTranscriptWordsPerMinute:
          (limits['min_transcript_words_per_minute'] as num).toDouble(),
      minAverageWordConfidence: (limits['min_avg_word_confidence'] as num)
          .toDouble(),
      sections: (json['sections'] as List)
          .map(
            (section) =>
                GuardrailSection.fromJson(section as Map<String, dynamic>),
          )
          .toList(),
    );
  }
}

class GuardrailSection {
  const GuardrailSection({required this.title, required this.items});

  final String title;
  final List<String> items;

  factory GuardrailSection.fromJson(Map<String, dynamic> json) {
    return GuardrailSection(
      title: json['title'] as String,
      items: List<String>.from(json['items'] as List),
    );
  }
}
