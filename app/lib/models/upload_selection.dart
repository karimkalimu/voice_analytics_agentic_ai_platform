class UploadSelection {
  const UploadSelection({
    required this.id,
    required this.userId,
    required this.originalName,
    required this.localPath,
    required this.layer2Options,
    required this.uniqueNouns,
    required this.topic,
    required this.createdAt,
  });

  final String id;
  final String userId;
  final String originalName;
  final String localPath;
  final List<String> layer2Options;
  final bool uniqueNouns;
  final String topic;
  final int createdAt;

  Map<String, dynamic> toJson() => {
    'id': id,
    'user_id': userId,
    'original_name': originalName,
    'local_path': localPath,
    'layer2_options': layer2Options,
    'unique_nouns': uniqueNouns,
    'topic': topic,
    'created_at': createdAt,
  };

  factory UploadSelection.fromJson(Map<String, dynamic> json) {
    return UploadSelection(
      id: json['id'] as String,
      userId: json['user_id'] as String,
      originalName: json['original_name'] as String,
      localPath: json['local_path'] as String,
      layer2Options: List<String>.from(json['layer2_options'] as List),
      uniqueNouns: json['unique_nouns'] as bool,
      topic: json['topic'] as String,
      createdAt: json['created_at'] as int,
    );
  }
}
