import 'package:flutter/material.dart';

import '../models.dart';
import '../services/api_service.dart';

class DetailScreen extends StatefulWidget {
  const DetailScreen({super.key, required this.session, required this.item});

  final UserSession session;
  final AnalysisItem item;

  @override
  State<DetailScreen> createState() => _DetailScreenState();
}

class _DetailScreenState extends State<DetailScreen> {
  final _api = ApiService();
  late Future<Map<String, dynamic>> _detailFuture;
  Map<String, dynamic>? _lessonNote;
  Map<String, dynamic>? _miniQuiz;
  List<QuizQuestion> _quizQuestions = [];
  final Map<int, String> _selectedQuizAnswers = {};
  bool _lessonNoteLoading = false;
  bool _miniQuizLoading = false;
  String? _lessonNoteError;
  String? _miniQuizError;

  @override
  void initState() {
    super.initState();
    _detailFuture = _api.getAnalysisDetail(
      kullaniciId: widget.session.kullaniciId,
      videoId: widget.item.videoId,
    );
  }

  Future<void> _loadLessonNote() async {
    setState(() {
      _lessonNoteLoading = true;
      _lessonNoteError = null;
    });

    try {
      final data = await _api.getLessonNote(videoId: widget.item.videoId);

      if (!mounted) return;
      setState(() => _lessonNote = data);
    } catch (error) {
      if (!mounted) return;
      setState(() => _lessonNoteError = error.toString());
    } finally {
      if (mounted) {
        setState(() => _lessonNoteLoading = false);
      }
    }
  }

  Future<void> _loadMiniQuiz() async {
    setState(() {
      _miniQuizLoading = true;
      _miniQuizError = null;
    });

    try {
      final data = await _api.getMiniQuiz(videoId: widget.item.videoId);
      final rawQuestions = data['sorular'];
      final questions = rawQuestions is List
          ? rawQuestions
              .whereType<Map<String, dynamic>>()
              .map(QuizQuestion.fromJson)
              .toList()
          : <QuizQuestion>[];

      if (!mounted) return;
      setState(() {
        _miniQuiz = data;
        _quizQuestions = questions;
        _selectedQuizAnswers.clear();
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _miniQuizError = error.toString());
    } finally {
      if (mounted) {
        setState(() => _miniQuizLoading = false);
      }
    }
  }

  void _selectAnswer(int questionIndex, String answer) {
    setState(() => _selectedQuizAnswers[questionIndex] = answer);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: _gradientDecoration(),
        child: SafeArea(
          child: FutureBuilder<Map<String, dynamic>>(
            future: _detailFuture,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }

              if (snapshot.hasError) {
                return _screenFrame(
                  child: _messagePanel(
                    'Detay alınamadı: ${snapshot.error}',
                    isError: true,
                  ),
                );
              }

              final data = snapshot.data ?? {};
              final video =
                  (data['video'] as Map?)?.cast<String, dynamic>() ?? {};
              final rawSegments = data['segmentler'];
              final segments = rawSegments is List
                  ? rawSegments
                      .whereType<Map<String, dynamic>>()
                      .map(SegmentItem.fromJson)
                      .toList()
                  : <SegmentItem>[];

              return _screenFrame(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _videoInfoPanel(video),
                    const SizedBox(height: 16),
                    _lessonNotePanel(),
                    const SizedBox(height: 16),
                    _miniQuizPanel(),
                    const SizedBox(height: 22),
                    Text(
                      'Atlanacak Segmentler (${segments.length})',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            color: const Color(0xFF4B5563),
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                    const SizedBox(height: 12),
                    if (segments.isEmpty)
                      _messagePanel('Bu video için segment bulunmadı.')
                    else
                      ...segments.map(_segmentPanel),
                  ],
                ),
              );
            },
          ),
        ),
      ),
    );
  }

  Widget _screenFrame({required Widget child}) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(22, 12, 22, 28),
      children: [
        Row(
          children: [
            _roundIconButton(
              icon: Icons.arrow_back_ios_new,
              tooltip: 'Geri',
              onPressed: () => Navigator.of(context).maybePop(),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                'Video Detayı',
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                      color: Colors.black,
                      fontFamily: 'serif',
                      fontWeight: FontWeight.w700,
                    ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 40),
        child,
      ],
    );
  }

  Widget _videoInfoPanel(Map<String, dynamic> video) {
    final title = (video['baslik'] ?? widget.item.baslik).toString();
    final description =
        (video['kisa_aciklama'] ?? widget.item.kisaAciklama).toString();
    final language = (video['dil'] ?? widget.item.dil).toString();
    final analysisDate =
        (video['analiz_tarihi'] ?? widget.item.analizTarihi).toString();

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: _panelDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            title,
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  color: Colors.black,
                  fontFamily: 'serif',
                  fontWeight: FontWeight.w700,
                  height: 1.18,
                ),
          ),
          if (description.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              description,
              style: const TextStyle(
                color: Color(0xFF6B7280),
                height: 1.35,
              ),
            ),
          ],
          const SizedBox(height: 16),
          _infoLine('Dil', language.isEmpty ? '-' : language),
          const SizedBox(height: 6),
          _infoLine('Analiz tarihi', analysisDate.isEmpty ? '-' : analysisDate),
        ],
      ),
    );
  }

  Widget _lessonNotePanel() {
    final noteText = (_lessonNote?['ders_notu'] ?? '').toString().trim();
    final source = (_lessonNote?['kaynak'] ?? '').toString();

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: _panelDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  'Ders Notu',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: Colors.black,
                        fontFamily: 'serif',
                        fontWeight: FontWeight.w700,
                      ),
                ),
              ),
              if (source.isNotEmpty)
                Text(
                  source == 'veritabani_cache' ? 'Kayıtlı' : 'Yeni',
                  style: const TextStyle(
                    color: Color(0xFF6B7280),
                    fontWeight: FontWeight.w600,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 12),
          if (_lessonNoteError != null) ...[
            Text(
              _lessonNoteError!,
              style: const TextStyle(
                color: Color(0xFFB42318),
                height: 1.35,
              ),
            ),
            const SizedBox(height: 12),
          ],
          if (noteText.isEmpty) ...[
            const Text(
              'Bu video için henüz ders notu oluşturulmadı.',
              style: TextStyle(
                color: Color(0xFF6B7280),
                height: 1.35,
              ),
            ),
            const SizedBox(height: 14),
            _pillButton(
              text: 'Ders Notu Oluştur',
              loading: _lessonNoteLoading,
              onPressed: _loadLessonNote,
            ),
          ] else ...[
            SelectableText(
              noteText,
              style: const TextStyle(
                color: Color(0xFF374151),
                height: 1.38,
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _miniQuizPanel() {
    final source = (_miniQuiz?['kaynak'] ?? '').toString();

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: _panelDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  'Mini Quiz',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: Colors.black,
                        fontFamily: 'serif',
                        fontWeight: FontWeight.w700,
                      ),
                ),
              ),
              if (source.isNotEmpty)
                Text(
                  source == 'veritabani_cache' ? 'Kayıtlı' : 'Yeni',
                  style: const TextStyle(
                    color: Color(0xFF6B7280),
                    fontWeight: FontWeight.w600,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 12),
          if (_miniQuizError != null) ...[
            Text(
              _miniQuizError!,
              style: const TextStyle(
                color: Color(0xFFB42318),
                height: 1.35,
              ),
            ),
            const SizedBox(height: 12),
          ],
          if (_quizQuestions.isEmpty) ...[
            const Text(
              'Bu video için henüz mini quiz oluşturulmadı.',
              style: TextStyle(
                color: Color(0xFF6B7280),
                height: 1.35,
              ),
            ),
            const SizedBox(height: 14),
            _pillButton(
              text: 'Mini Quiz Oluştur',
              loading: _miniQuizLoading,
              onPressed: _loadMiniQuiz,
            ),
          ] else ...[
            ..._quizQuestions.asMap().entries.map(
                  (entry) => _quizQuestionPanel(entry.key, entry.value),
                ),
          ],
        ],
      ),
    );
  }

  Widget _quizQuestionPanel(int questionIndex, QuizQuestion question) {
    final selectedAnswer = _selectedQuizAnswers[questionIndex];
    final answered = selectedAnswer != null;
    final correct = selectedAnswer == question.dogruCevap;

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.62),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            '${questionIndex + 1}) ${question.soruMetni}',
            style: const TextStyle(
              color: Colors.black,
              fontWeight: FontWeight.w700,
              height: 1.3,
            ),
          ),
          const SizedBox(height: 10),
          ...['A', 'B', 'C'].map(
            (key) => _quizOptionButton(
              questionIndex: questionIndex,
              question: question,
              optionKey: key,
            ),
          ),
          if (answered) ...[
            const SizedBox(height: 10),
            Text(
              correct
                  ? 'Doğru cevap.'
                  : 'Yanlış cevap. Doğru cevap: ${question.dogruCevap}',
              style: TextStyle(
                color:
                    correct ? const Color(0xFF047857) : const Color(0xFFB42318),
                fontWeight: FontWeight.w700,
              ),
            ),
            if (question.aciklama.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                question.aciklama,
                style: const TextStyle(
                  color: Color(0xFF6B7280),
                  height: 1.3,
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }

  Widget _quizOptionButton({
    required int questionIndex,
    required QuizQuestion question,
    required String optionKey,
  }) {
    final selectedAnswer = _selectedQuizAnswers[questionIndex];
    final selected = selectedAnswer == optionKey;
    final answered = selectedAnswer != null;
    final correctOption = question.dogruCevap == optionKey;
    Color backgroundColor = Colors.white.withValues(alpha: 0.72);
    Color borderColor = Colors.transparent;

    if (answered && correctOption) {
      backgroundColor = const Color(0xFFD1FAE5);
      borderColor = const Color(0xFF10B981);
    } else if (answered && selected && !correctOption) {
      backgroundColor = const Color(0xFFFEE2E2);
      borderColor = const Color(0xFFEF4444);
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: backgroundColor,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: () => _selectAnswer(questionIndex, optionKey),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: borderColor),
            ),
            child: Text(
              '$optionKey) ${question.secenekler[optionKey] ?? ''}',
              style: const TextStyle(
                color: Color(0xFF374151),
                fontWeight: FontWeight.w600,
                height: 1.25,
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _pillButton({
    required String text,
    required bool loading,
    required VoidCallback onPressed,
  }) {
    return SizedBox(
      height: 46,
      child: FilledButton(
        style: FilledButton.styleFrom(
          backgroundColor: Colors.white,
          foregroundColor: Colors.black,
          disabledBackgroundColor: Colors.white.withValues(alpha: 0.72),
          shape: const StadiumBorder(),
          elevation: 0,
          textStyle: const TextStyle(fontWeight: FontWeight.w700),
        ),
        onPressed: loading ? null : onPressed,
        child: loading
            ? const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : Text(text),
      ),
    );
  }

  Widget _segmentPanel(SegmentItem segment) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: _panelDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '${_formatTime(segment.start)} - ${_formatTime(segment.end)}',
                  style: const TextStyle(
                    color: Colors.black,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 5,
                ),
                decoration: BoxDecoration(
                  color: const Color(0xFFDDEEFF).withValues(alpha: 0.75),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  segment.score.toStringAsFixed(2),
                  style: const TextStyle(
                    color: Color(0xFF374151),
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          if (segment.text.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              segment.text,
              style: const TextStyle(
                color: Color(0xFF6B7280),
                height: 1.32,
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _infoLine(String label, String value) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 96,
          child: Text(
            label,
            style: const TextStyle(
              color: Color(0xFF6B7280),
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: const TextStyle(color: Color(0xFF374151)),
          ),
        ),
      ],
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
      decoration: _panelDecoration(),
      child: Text(
        text,
        style: TextStyle(
          color: isError ? const Color(0xFFB42318) : const Color(0xFF6B7280),
          height: 1.35,
        ),
      ),
    );
  }

  BoxDecoration _gradientDecoration() {
    return const BoxDecoration(
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
    );
  }

  BoxDecoration _panelDecoration() {
    return BoxDecoration(
      color: Colors.white.withValues(alpha: 0.76),
      borderRadius: BorderRadius.circular(8),
      boxShadow: [
        BoxShadow(
          color: Colors.black.withValues(alpha: 0.045),
          blurRadius: 18,
          offset: const Offset(0, 10),
        ),
      ],
    );
  }

  String _formatTime(double seconds) {
    final total = seconds.round();
    final minutes = total ~/ 60;
    final remainingSeconds = total % 60;
    return '$minutes:${remainingSeconds.toString().padLeft(2, '0')}';
  }
}
