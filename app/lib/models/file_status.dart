const activeFileStatuses = {
  'uploaded',
  'validating_audio',
  'transcribing',
  'validating_transcript',
  'transcribed',
  'analyzing',
  'analyzing_layer2',
};

bool isActiveFileStatus(String status) => activeFileStatuses.contains(status);
