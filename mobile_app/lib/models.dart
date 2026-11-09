class UserSession {
  const UserSession({
    required this.kullaniciId,
    required this.ad,
    required this.email,
  });

  final int kullaniciId;
  final String ad;
  final String email;
}

class AnalysisItem {
  const AnalysisItem({
    required this.analizId,
    required this.videoId,
    required this.youtubeVideoId,
    required this.videoUrl,
    required this.baslik,
    required this.kisaAciklama,
    required this.analizTarihi,
    required this.dil,
  });

  final int analizId;
  final int videoId;
  final String youtubeVideoId;
  final String videoUrl;
  final String baslik;
  final String kisaAciklama;
  final String analizTarihi;
  final String dil;

  factory AnalysisItem.fromJson(Map<String, dynamic> json) {
    return AnalysisItem(
      analizId: json['analiz_id'] ?? 0,
      videoId: json['video_id'] ?? 0,
      youtubeVideoId: json['youtube_video_id'] ?? '',
      videoUrl: json['video_url'] ?? '',
      baslik: json['baslik'] ?? 'Başlık yok',
      kisaAciklama: json['kisa_aciklama'] ?? '',
      analizTarihi: json['analiz_tarihi'] ?? '',
      dil: json['dil'] ?? '',
    );
  }
}

class SegmentItem {
  const SegmentItem({
    required this.start,
    required this.end,
    required this.text,
    required this.score,
  });

  final double start;
  final double end;
  final String text;
  final double score;

  factory SegmentItem.fromJson(Map<String, dynamic> json) {
    return SegmentItem(
      start: _toDouble(json['start']),
      end: _toDouble(json['end']),
      text: json['text'] ?? '',
      score: _toDouble(json['score'] ?? json['skip_score']),
    );
  }
}

class QuizQuestion {
  const QuizQuestion({
    required this.quizSoruId,
    required this.soruMetni,
    required this.secenekler,
    required this.dogruCevap,
    required this.aciklama,
  });

  final int quizSoruId;
  final String soruMetni;
  final Map<String, String> secenekler;
  final String dogruCevap;
  final String aciklama;

  factory QuizQuestion.fromJson(Map<String, dynamic> json) {
    final rawOptions = json['secenekler'];
    final options = <String, String>{
      'A': json['secenek_a'] ?? '',
      'B': json['secenek_b'] ?? '',
      'C': json['secenek_c'] ?? '',
    };

    if (rawOptions is Map) {
      options['A'] = rawOptions['A']?.toString() ?? options['A'] ?? '';
      options['B'] = rawOptions['B']?.toString() ?? options['B'] ?? '';
      options['C'] = rawOptions['C']?.toString() ?? options['C'] ?? '';
    }

    return QuizQuestion(
      quizSoruId: json['quiz_soru_id'] ?? 0,
      soruMetni: json['soru_metni'] ?? '',
      secenekler: options,
      dogruCevap: (json['dogru_cevap'] ?? '').toString().toUpperCase(),
      aciklama: json['aciklama'] ?? '',
    );
  }
}

double _toDouble(dynamic value) {
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value) ?? 0;
  return 0;
}
