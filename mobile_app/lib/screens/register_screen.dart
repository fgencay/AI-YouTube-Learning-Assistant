import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../services/session_service.dart';
import 'home_screen.dart';

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _nameController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _api = ApiService();
  final _sessionService = SessionService();
  bool _loading = false;
  String? _error;

  @override
  void dispose() {
    _nameController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _register() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final session = await _api.register(
        ad: _nameController.text,
        email: _emailController.text,
        sifre: _passwordController.text,
      );
      await _sessionService.save(session);

      if (!mounted) return;
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => HomeScreen(session: session)),
        (_) => false,
      );
    } catch (error) {
      setState(() => _error = error.toString());
    } finally {
      if (mounted) {
        setState(() => _loading = false);
      }
    }
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
                          'Kayıt Ol',
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
                        const SizedBox(height: 104),
                        TextField(
                          controller: _nameController,
                          textAlign: TextAlign.center,
                          decoration: _lineInputDecoration('Ad'),
                        ),
                        const SizedBox(height: 22),
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
                            _error!,
                            textAlign: TextAlign.center,
                            style: const TextStyle(color: Color(0xFFB42318)),
                          ),
                        ],
                        const SizedBox(height: 64),
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
                            onPressed: _loading ? null : _register,
                            child: _loading
                                ? const SizedBox(
                                    width: 18,
                                    height: 18,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Text('Kayıt Ol'),
                          ),
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
