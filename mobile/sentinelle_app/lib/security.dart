import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:local_auth/local_auth.dart';

import 'api.dart';

/// Stockage chiffré par le Keystore Android. Rien de sensible en clair sur le téléphone.
class SecureStore implements TokenStore {
  SecureStore() : _s = const FlutterSecureStorage();
  final FlutterSecureStorage _s;

  static const _kServer = 'server_url';
  static const _kRefresh = 'refresh_token';

  Future<String?> readServer() => _s.read(key: _kServer);
  Future<void> writeServer(String url) => _s.write(key: _kServer, value: url);

  @override
  Future<String?> readRefreshToken() => _s.read(key: _kRefresh);

  @override
  Future<void> writeRefreshToken(String? token) =>
      token == null ? _s.delete(key: _kRefresh) : _s.write(key: _kRefresh, value: token);

  Future<void> wipe() => _s.deleteAll();
}

/// Déverrouillage par empreinte / visage (ou code du téléphone en secours).
class Biometrics {
  final LocalAuthentication _auth = LocalAuthentication();

  Future<bool> unlock(String reason) async {
    try {
      final supported = await _auth.isDeviceSupported();
      if (!supported) return false; // pas de verrou sur le téléphone : on refuse
      return await _auth.authenticate(localizedReason: reason);
    } catch (_) {
      return false;
    }
  }
}
