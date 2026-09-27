class UploadedFile {
  const UploadedFile({
    required this.id,
    required this.userId,
    required this.uploadId,
    required this.originalName,
    required this.storagePath,
    required this.status,
    required this.createdAt,
    required this.language,
    required this.error,
    required this.rejectionCode,
    required this.guardrailVersion,
    required this.transcriptPath,
    required this.transcriptAvailable,
    required this.durationSec,
    required this.summary,
    required this.professionalTopics,
    required this.personalTopics,
    required this.upcomingEvents,
    required this.audioSha256,
    required this.transcriptionVersion,
    required this.analysisVersion,
    required this.layer2Options,
    required this.layer2Config,
    required this.layer2Results,
    required this.layer2Version,
  });

  final int id;
  final String userId;
  final String uploadId;
  final String originalName;
  final String storagePath;
  final String status;
  final String createdAt;
  final String? language;
  final String? error;
  final String? rejectionCode;
  final String? guardrailVersion;
  final String? transcriptPath;
  final bool transcriptAvailable;
  final double? durationSec;
  final String? summary;
  final List<String> professionalTopics;
  final List<String> personalTopics;
  final List<String> upcomingEvents;
  final String? audioSha256;
  final String? transcriptionVersion;
  final String? analysisVersion;
  final List<String> layer2Options;
  final Map<String, dynamic> layer2Config;
  final Map<String, dynamic> layer2Results;
  final Map<String, dynamic> layer2Version;

  factory UploadedFile.fromJson(Map<String, dynamic> json) {
    return UploadedFile(
      id: json['id'] as int,
      userId: json['user_id'] as String,
      uploadId: json['upload_id'] as String,
      originalName: json['original_name'] as String,
      storagePath: json['storage_path'] as String,
      status: json['status'] as String,
      createdAt: json['created_at'] as String,
      language: json['language'] as String?,
      error: json['error'] as String?,
      rejectionCode: json['rejection_code'] as String?,
      guardrailVersion: json['guardrail_version'] as String?,
      transcriptPath: json['transcript_path'] as String?,
      transcriptAvailable: json['transcript_available'] as bool,
      durationSec: (json['duration_sec'] as num?)?.toDouble(),
      summary: json['summary'] as String?,
      professionalTopics: List<String>.from(
        json['professional_topics'] as List,
      ),
      personalTopics: List<String>.from(json['personal_topics'] as List),
      upcomingEvents: List<String>.from(json['upcoming_events'] as List),
      audioSha256: json['audio_sha256'] as String?,
      transcriptionVersion: json['transcription_version'] as String?,
      analysisVersion: json['analysis_version'] as String?,
      layer2Options: List<String>.from(json['layer2_options'] as List),
      layer2Config: Map<String, dynamic>.from(json['layer2_config'] as Map),
      layer2Results: Map<String, dynamic>.from(json['layer2_results'] as Map),
      layer2Version: Map<String, dynamic>.from(json['layer2_version'] as Map),
    );
  }
}
