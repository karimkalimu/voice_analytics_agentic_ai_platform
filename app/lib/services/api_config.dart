class ApiConfig {
  static const host = String.fromEnvironment(
    'BACKEND_HOST',
    defaultValue: 'localhost',
    // defaultValue: 'localhost',
  );

  static const fastApiBaseUrl = 'http://$host:8000';
  static const tusdBaseUrl = 'http://$host:8081';
}
