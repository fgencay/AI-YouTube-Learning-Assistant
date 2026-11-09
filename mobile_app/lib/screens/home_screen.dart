import 'package:flutter/material.dart';

import '../models.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';
import 'detail_screen.dart';
import 'login_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.session});

  final UserSession session;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _api = ApiService();
  late Future<List<AnalysisItem>> _analysesFuture;

  @override
  void initState() {
    super.initState();
    _analysesFuture = _api.getAnalyses(widget.session.kullaniciId);
  }

  void _refresh() {
    setState(() {
      _analysesFuture = _api.getAnalyses(widget.session.kullaniciId);
    });
  }

  Future<void> _logout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => Dialog(
        backgroundColor: Colors.transparent,
        insetPadding: const EdgeInsets.symmetric(horizontal: 28),
        child: Container(
          padding: const EdgeInsets.fromLTRB(22, 22, 22, 18),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            gradient: const LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [
                Color(0xFFFFFBF7),
                Color(0xFFFDF8F4),
                Color(0xFFDDEEFF),
              ],
            ),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.08),
                blurRadius: 24,
                offset: const Offset(0, 14),
              ),
            ],
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Çıkış Yap',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      color: Colors.black,
                      fontFamily: 'serif',
                      fontWeight: FontWeight.w700,
                    ),
              ),
              const SizedBox(height: 14),
              const Text(
                'Oturumu kapatmak istiyor musun?',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: Color(0xFF6B7280),
                  height: 1.35,
                ),
              ),
              const SizedBox(height: 22),
              Row(
                children: [
                  Expanded(
                    child: TextButton(
                      style: TextButton.styleFrom(
                        foregroundColor: const Color(0xFF6B7280),
                        shape: const StadiumBorder(),
                      ),
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('Vazgeç'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: Colors.white,
                        foregroundColor: Colors.black,
                        elevation: 0,
                        shape: const StadiumBorder(),
                      ),
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('Çıkış'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );

    if (confirmed != true) return;

    await SessionService().clear();

    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              Color(0xFFFFFBF7),
              Color(0xFFFDF8F4),
              Color(0xFFDDEEFF),
              Color(0xFFFFF8F2),
            ],
            stops: [0.0, 0.34, 0.72, 1.0],
          ),
        ),
        child: SafeArea(
          child: RefreshIndicator(
            color: Colors.black87,
            onRefresh: () async => _refresh(),
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(22, 12, 22, 28),
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        'Analizlerim',
                        style:
                            Theme.of(context).textTheme.headlineSmall?.copyWith(
                                  color: Colors.black,
                                  fontFamily: 'serif',
                                  fontWeight: FontWeight.w700,
                                ),
                      ),
                    ),
                    _roundIconButton(
                      icon: Icons.refresh,
                      tooltip: 'Yenile',
                      onPressed: _refresh,
                    ),
                    const SizedBox(width: 8),
                    _roundIconButton(
                      icon: Icons.logout,
                      tooltip: 'Çıkış',
                      onPressed: _logout,
                    ),
                  ],
                ),
                const SizedBox(height: 42),
                Text(
                  'Merhaba, ${widget.session.ad}',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        color: Colors.black,
                        fontFamily: 'serif',
                        fontWeight: FontWeight.w700,
                      ),
                ),
                const SizedBox(height: 34),
                Text(
                  'Video Geçmişi',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: const Color(0xFF4B5563),
                        fontWeight: FontWeight.w700,
                      ),
                ),
                const SizedBox(height: 12),
                FutureBuilder<List<AnalysisItem>>(
                  future: _analysesFuture,
                  builder: (context, snapshot) {
                    if (snapshot.connectionState != ConnectionState.done) {
                      return const Center(
                        child: Padding(
                          padding: EdgeInsets.all(32),
                          child: CircularProgressIndicator(),
                        ),
                      );
                    }

                    if (snapshot.hasError) {
                      return _messagePanel(
                        'Geçmiş alınamadı: ${snapshot.error}',
                        isError: true,
                      );
                    }

                    final analyses = snapshot.data ?? [];

                    if (analyses.isEmpty) {
                      return _messagePanel(
                        'Henüz analiz edilen video yok. Chrome eklentisinde giriş yapıp video analiz ettikten sonra burada görünecek.',
                      );
                    }

                    return Column(
                      children: analyses
                          .map(
                            (item) => Container(
                              margin: const EdgeInsets.only(bottom: 10),
                              decoration: BoxDecoration(
                                color: Colors.white.withValues(alpha: 0.76),
                                borderRadius: BorderRadius.circular(8),
                                boxShadow: [
                                  BoxShadow(
                                    color:
                                        Colors.black.withValues(alpha: 0.045),
                                    blurRadius: 18,
                                    offset: const Offset(0, 10),
                                  ),
                                ],
                              ),
                              child: ListTile(
                                contentPadding: const EdgeInsets.symmetric(
                                  horizontal: 16,
                                  vertical: 8,
                                ),
                                title: Text(
                                  item.baslik,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                    color: Colors.black,
                                  ),
                                ),
                                subtitle: Padding(
                                  padding: const EdgeInsets.only(top: 6),
                                  child: Text(
                                    item.kisaAciklama.isEmpty
                                        ? item.analizTarihi
                                        : item.kisaAciklama,
                                    maxLines: 3,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      color: Color(0xFF6B7280),
                                      height: 1.3,
                                    ),
                                  ),
                                ),
                                trailing: const Icon(Icons.chevron_right),
                                onTap: () {
                                  Navigator.of(context).push(
                                    MaterialPageRoute(
                                      builder: (_) => DetailScreen(
                                        session: widget.session,
                                        item: item,
                                      ),
                                    ),
                                  );
                                },
                              ),
                            ),
                          )
                          .toList(),
                    );
                  },
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _roundIconButton({
    required IconData icon,
    required String tooltip,
    required VoidCallback onPressed,
  }) {
    return Tooltip(
      message: tooltip,
      child: Material(
        color: Colors.white.withValues(alpha: 0.78),
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: onPressed,
          child: SizedBox(
            width: 42,
            height: 42,
            child: Icon(
              icon,
              color: Colors.black87,
              size: 21,
            ),
          ),
        ),
      ),
    );
  }

  Widget _messagePanel(String text, {bool isError = false}) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        text,
        style: TextStyle(
          color: isError ? const Color(0xFFB42318) : const Color(0xFF6B7280),
          height: 1.35,
        ),
      ),
    );
  }
}
