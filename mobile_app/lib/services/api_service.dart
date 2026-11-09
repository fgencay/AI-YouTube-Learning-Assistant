import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models.dart';

class ApiException implements Exception {
  ApiException(this.message, {this.waitSeconds = 0});

  final String message;
  final int waitSeconds;

  @override
  String toString() => message;
}

class ApiService {
  static const baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );

  Future<UserSession> register({
    required String ad,
    required String email,
    required String sifre,
  }) async {
    final data = await _post('/api/kayit', {
      'ad': ad,
      'email': email,
      'sifre': sifre,
    });

    return _sessionFromResponse(data);
  }

  Future<UserSession> login({
    required String email,
    required String sifre,
  }) async {
    final data = await _post('/api/giris', {'email': email, 'sifre': sifre});

    return _sessionFromResponse(data);
  }

  Future<List<AnalysisItem>> getAnalyses(int kullaniciId) async {
    final data = await _get('/api/kullanicilar/$kullaniciId/analizler');
    final list = data['analizler'];

    if (list is! List) {
      return [];
    }

    return list
        .whereType<Map<String, dynamic>>()
        .map(AnalysisItem.fromJson)
        .toList();
  }

  Future<Map<String, dynamic>> getAnalysisDetail({
    required int kullaniciId,
    required int videoId,
  }) {
    return _get('/api/kullanicilar/$kullaniciId/analizler/$videoId');
  }

  Future<Map<String, dynamic>> getLessonNote({
    required int videoId,
  }) {
    return _get('/api/videolar/$videoId/ders-notu');
  }

  Future<Map<String, dynamic>> getMiniQuiz({
    required int videoId,
  }) {
    return _get('/api/videolar/$videoId/mini-quiz');
  }

  UserSession _sessionFromResponse(Map<String, dynamic> data) {
    return UserSession(
      kullaniciId: data['kullanici_id'] ?? 0,
      ad: data['ad'] ?? '',
      email: data['email'] ?? '',
    );
  }

  Future<Map<String, dynamic>> _get(String path) async {
    final response = await http.get(Uri.parse('$baseUrl$path'));
    return _decode(response);
  }

  Future<Map<String, dynamic>> _post(
    String path,
    Map<String, dynamic> body,
  ) async {
    final response = await http.post(
      Uri.parse('$baseUrl$path'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );

    return _decode(response);
  }

  Map<String, dynamic> _decode(http.Response response) {
    final data =
        jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;

    if (response.statusCode >= 400 || data['durum'] == 'hata') {
      throw ApiException(
        data['mesaj'] ?? 'İşlem başarısız oldu.',
        waitSeconds: data['bekleme_suresi'] ?? 0,
      );
    }

    return data;
  }
}
