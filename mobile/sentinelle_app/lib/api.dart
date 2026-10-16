import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// Erreur lisible renvoyée par le serveur ou le réseau.
class ApiException implements Exception {
  ApiException(this.statusCode, this.message);
  final int statusCode;
  final String message;
  @override
  String toString() => message;
}

/// Stockage des jetons (implémenté par SecureStore ; remplaçable en test).
abstract class TokenStore {
  Future<String?> readRefreshToken();
  Future<void> writeRefreshToken(String? token);
}

/// Client de l'API SENTINELLE.
/// - HTTPS obligatoire (sauf adresse locale, pour les tests) ;
/// - jeton d'accès court en mémoire seulement ; jeton de rafraîchissement dans le Keystore ;
/// - un 401 déclenche UN rafraîchissement puis UNE nouvelle tentative.
class ApiClient {
  ApiClient({required String baseUrl, required this.tokens, http.Client? httpClient})
      : baseUri = _validate(baseUrl),
        _http = httpClient ?? http.Client();

  final Uri baseUri;
  final TokenStore tokens;
  final http.Client _http;
  String? _accessToken;
  static const _timeout = Duration(seconds: 15);

  static Uri _validate(String raw) {
    final uri = Uri.tryParse(raw.trim());
    if (uri == null || uri.host.isEmpty) {
      throw ApiException(0, 'Adresse du serveur invalide.');
    }
    final local = uri.host == 'localhost' || uri.host == '127.0.0.1' || uri.host == '10.0.2.2';
    if (uri.scheme != 'https' && !local) {
      throw ApiException(0, 'Connexion refusée : HTTPS obligatoire.');
    }
    return uri.replace(path: uri.path.endsWith('/') ? uri.path.substring(0, uri.path.length - 1) : uri.path);
  }

  Uri _u(String path, [Map<String, String>? query]) =>
      baseUri.replace(path: '${baseUri.path}$path', queryParameters: query);

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_accessToken != null) 'Authorization': 'Bearer $_accessToken',
      };

  dynamic _decode(http.Response r) {
    final body = r.body.isEmpty ? null : jsonDecode(utf8.decode(r.bodyBytes));
    if (r.statusCode >= 200 && r.statusCode < 300) return body;
    var message = 'Erreur ${r.statusCode}';
    if (body is Map && body['detail'] != null) {
      final d = body['detail'];
      message = d is String ? d : 'Requête invalide.';
    }
    throw ApiException(r.statusCode, message);
  }

  Future<void> _saveTokens(Map<String, dynamic> t) async {
    _accessToken = t['access_token'] as String;
    await tokens.writeRefreshToken(t['refresh_token'] as String);
  }

  Future<void> login(String password) async {
    final r = await _http
        .post(_u('/auth/login'), headers: {'Content-Type': 'application/json'}, body: jsonEncode({'password': password}))
        .timeout(_timeout);
    await _saveTokens(_decode(r) as Map<String, dynamic>);
  }

  /// Renouvelle la session avec le jeton stocké. Retourne false si la session est perdue.
  Future<bool> refresh() async {
    final rt = await tokens.readRefreshToken();
    if (rt == null) return false;
    final r = await _http
        .post(_u('/auth/refresh'), headers: {'Content-Type': 'application/json'}, body: jsonEncode({'refresh_token': rt}))
        .timeout(_timeout);
    if (r.statusCode != 200) {
      await tokens.writeRefreshToken(null);
      _accessToken = null;
      return false;
    }
    await _saveTokens(jsonDecode(r.body) as Map<String, dynamic>);
    return true;
  }

  Future<dynamic> _send(Future<http.Response> Function() call) async {
    try {
      var r = await call().timeout(_timeout);
      if (r.statusCode == 401 && await refresh()) {
        r = await call().timeout(_timeout);
      }
      return _decode(r);
    } on TimeoutException {
      throw ApiException(0, 'Le serveur ne répond pas.');
    } on http.ClientException {
      throw ApiException(0, 'Pas de connexion au serveur.');
    }
  }

  Future<dynamic> get(String path, {Map<String, String>? query}) =>
      _send(() => _http.get(_u(path, query), headers: _headers));

  Future<dynamic> post(String path, [Map<String, dynamic>? body]) =>
      _send(() => _http.post(_u(path), headers: _headers, body: jsonEncode(body ?? {})));

  Future<void> logoutEverywhere() async {
    try {
      await post('/auth/logout-all');
    } finally {
      _accessToken = null;
      await tokens.writeRefreshToken(null);
    }
  }

  // Raccourcis métier
  Future<Map<String, dynamic>> status() async => (await get('/status')) as Map<String, dynamic>;
  Future<Map<String, dynamic>> trades() async => (await get('/trades')) as Map<String, dynamic>;
  Future<List<dynamic>> strategies() async => (await get('/strategies')) as List<dynamic>;
  Future<Map<String, dynamic>> strategy(String name) async =>
      (await get('/strategies/${Uri.encodeComponent(name)}')) as Map<String, dynamic>;
  Future<Map<String, dynamic>> risk() async => (await get('/risk')) as Map<String, dynamic>;
  Future<List<dynamic>> events() async => (await get('/events', query: {'limit': '100'})) as List<dynamic>;
  Future<List<dynamic>> deposits() async => (await get('/deposits')) as List<dynamic>;
}
