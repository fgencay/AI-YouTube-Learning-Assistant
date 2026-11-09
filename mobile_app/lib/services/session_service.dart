import 'package:shared_preferences/shared_preferences.dart';

import '../models.dart';

class SessionService {
  static const _kullaniciIdKey = 'kullanici_id';
  static const _adKey = 'ad';
  static const _emailKey = 'email';

  Future<void> save(UserSession session) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_kullaniciIdKey, session.kullaniciId);
    await prefs.setString(_adKey, session.ad);
    await prefs.setString(_emailKey, session.email);
  }

  Future<UserSession?> load() async {
    final prefs = await SharedPreferences.getInstance();
    final kullaniciId = prefs.getInt(_kullaniciIdKey);

    if (kullaniciId == null) {
      return null;
    }

    return UserSession(
      kullaniciId: kullaniciId,
      ad: prefs.getString(_adKey) ?? '',
      email: prefs.getString(_emailKey) ?? '',
    );
  }

  Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kullaniciIdKey);
    await prefs.remove(_adKey);
    await prefs.remove(_emailKey);
  }
}
