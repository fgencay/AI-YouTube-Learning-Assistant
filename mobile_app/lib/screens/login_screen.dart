import 'dart:async';

import 'package:flutter/material.dart';

import '../models.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';
import 'home_screen.dart';
import 'register_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _api = ApiService();
  final _sessionService = SessionService();
  bool _loading = false;
  String? _error;
  int _remainingWaitSeconds = 0;
  Timer? _countdownTimer;

  @override
  void dispose() {
    _countdownTimer?.cancel();
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  void _startLoginCountdown(int seconds) {
    _countdownTimer?.cancel();

    setState(() {
      _remainingWaitSeconds = seconds;
      _error = 'E-mail veya şifre hatalı';
    });

    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }

      if (_remainingWaitSeconds <= 1) {
        timer.cancel();
        setState(() {
          _remainingWaitSeconds = 0;
        });
        return;
      }

      setState(() {
        _remainingWaitSeconds -= 1;
      });
    });
  }

  Future<void> _login() async {
    if (_remainingWaitSeconds > 0) {
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final session = await _api.login(
        email: _emailController.text,
        sifre: _passwordController.text,
      );
      _countdownTimer?.cancel();
      await _sessionService.save(session);

      if (!mounted) return;
      _openHome(session);
    } on ApiException catch (error) {
      if (error.waitSeconds > 0) {
        _startLoginCountdown(error.waitSeconds);
      } else {
        setState(() => _error = error.toString());
      }
    } catch (error) {
      setState(() => _error = error.toString());
    } finally {
      if (mounted) {
        setState(() => _loading = false);
      }
    }
  }

  void _openHome(UserSession session) {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => HomeScreen(session: session)),
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
          child: Stack(
            children: [
              Positioned(
                left: 8,
                top: 8,
                child: IconButton(
                  onPressed: () => Navigator.of(context).maybePop(),
                  icon: const Icon(Icons.arrow_back_ios_new),
                  color: Colors.black87,
                ),
              ),
              Center(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.symmetric(horizontal: 42),
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 420),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          'Öğrenci Video Asistanı',
                          textAlign: TextAlign.center,
                          style: Theme.of(context)
                              .textTheme
                              .headlineSmall
                              ?.copyWith(
                                color: Colors.black,
                                fontFamily: 'serif',
                                fontWeight: FontWeight.w700,
                                height: 1.15,
                              ),
                        ),
                        const SizedBox(height: 12),
                        Text(
                          'Analiz ettiğin eğitim videolarını takip et.',
                          textAlign: TextAlign.center,
                          style:
                              Theme.of(context).textTheme.bodyMedium?.copyWith(
                                    color: const Color(0xFF6E7580),
                                    letterSpacing: 0,
                                  ),
                        ),
                        const SizedBox(height: 92),
                        TextField(
                          controller: _emailController,
                          keyboardType: TextInputType.emailAddress,
                          textAlign: TextAlign.center,
                          decoration: _lineInputDecoration('Email'),
                        ),
                        const SizedBox(height: 22),
                        TextField(
                          controller: _passwordController,
                          obscureText: true,
                          textAlign: TextAlign.center,
                          decoration: _lineInputDecoration('Şifre'),
                        ),
                        if (_error != null) ...[
                          const SizedBox(height: 18),
                          Text(
                            _remainingWaitSeconds > 0
                                ? '$_error\nTekrar denemek için $_remainingWaitSeconds sn'
                                : _error!,
                            textAlign: TextAlign.center,
                            style: const TextStyle(color: Color(0xFFB42318)),
                          ),
                        ],
                        const SizedBox(height: 72),
                        SizedBox(
                          height: 48,
                          child: FilledButton(
                            style: FilledButton.styleFrom(
                              backgroundColor: Colors.white,
                              foregroundColor: Colors.black,
                              disabledBackgroundColor:
                                  Colors.white.withValues(alpha: 0.72),
                              shape: const StadiumBorder(),
                              elevation: 0,
                              textStyle: const TextStyle(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            onPressed: (_loading || _remainingWaitSeconds > 0)
                                ? null
                                : _login,
                            child: _loading
                                ? const SizedBox(
                                    width: 18,
                                    height: 18,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Text('Giriş Yap'),
                          ),
                        ),
                        const SizedBox(height: 18),
                        TextButton(
                          onPressed: (_loading || _remainingWaitSeconds > 0)
                              ? null
                              : () {
                                  Navigator.of(context).push(
                                    MaterialPageRoute(
                                      builder: (_) => const RegisterScreen(),
                                    ),
                                  );
                                },
                          style: TextButton.styleFrom(
                            foregroundColor: const Color(0xFF7D858F),
                            textStyle: const TextStyle(
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          child: const Text('Hesabın yok mu? Kayıt ol'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  InputDecoration _lineInputDecoration(String label) {
    const border = UnderlineInputBorder(
      borderSide: BorderSide(color: Color(0xFF9EA4AA), width: 1.1),
    );

    return InputDecoration(
      labelText: label,
      floatingLabelBehavior: FloatingLabelBehavior.never,
      alignLabelWithHint: true,
      contentPadding: const EdgeInsets.only(bottom: 12),
      border: border,
      enabledBorder: border,
      focusedBorder: const UnderlineInputBorder(
        borderSide: BorderSide(color: Color(0xFF6E7781), width: 1.4),
      ),
      hintStyle: const TextStyle(
        color: Color(0xFF9299A1),
        fontSize: 16,
        letterSpacing: 0,
      ),
      labelStyle: const TextStyle(
        color: Color(0xFF9299A1),
        fontSize: 16,
        letterSpacing: 0,
      ),
    );
  }
}
