import json
import os
import re
import urllib.error
import urllib.request


REMOTE_LLM_URL = os.getenv(
    "REMOTE_LLM_URL",
    "http://127.0.0.1:8001/v1/chat/completions"
)
REMOTE_LLM_MODEL = os.getenv(
    "REMOTE_LLM_MODEL",
    "qwen2.5-14b-local-fp16"
)
REMOTE_LLM_TIMEOUT = int(os.getenv("REMOTE_LLM_TIMEOUT", "180"))


def transcript_chunklere_bol(transcript, chunk_size=20):
    chunkler = []

    for i in range(0, len(transcript), chunk_size):
        chunkler.append(transcript[i:i + chunk_size])

    return chunkler


def llm_ile_index_sec(aday_parcalar, video_basligi="", video_aciklamasi="", video_ozeti=""):
    transcript_satirlari = []

    for index, parca in enumerate(aday_parcalar, start=1):
        chapter = parca.get("chapter") or "Chapter bilgisi yok"
        reason = parca.get("reason") or "kural sinyali yok"
        skip_score = parca.get("skip_score", parca.get("score", 0.0))
        transcript_satirlari.append(
            f"{index}. Chapter: {chapter} | Skip skoru: {skip_score} | Neden: {reason} | Metin: {parca['text']}"
        )

    transcript_metni = "\n".join(transcript_satirlari)

    prompt = f"""
Sadece asagidaki formatta cevap ver:
[1, 3, 4]

Video basligi:
{video_basligi or "Bilinmeyen video"}

Video aciklamasi:
{(video_aciklamasi or "Aciklama yok")[:1500]}

Video kisa ozeti:
{video_ozeti or "Ozet yok"}

Gorev:
Bu aday satirlar, videonun tamamindan kural tabanli olarak secilmis olasi atlanabilir parcalardir.
Sadece ders acisindan guvenle atlanabilecek gereksiz bolumleri sec.

Secilebilecek bolumler:
- Sponsor, reklam, urun tanitimi
- Abone ol, begen, yorum yap, bildirimleri ac
- Aciklamadaki linke yonlendirme
- Giris muzigi, uzun intro, outro, kapanis

Kesinlikle secme:
- Tanim, konu anlatimi, ornek, kod aciklamasi
- Formul, ders anlatimi, teknik adim, kurulumun gerekli adimi
- Videonun ana konusunu ogreten herhangi bir metin

Kararsizsan secme. Sadece sayi listesi ver, aciklama yazma.

Transcript:
{transcript_metni}

Cevap:
"""

    uretilen_metin = remote_llm_cevap_al(
        prompt=prompt,
        max_tokens=40
    )
    print("LLM ham cevap:", uretilen_metin)

    return llm_indexlerini_parse_et(uretilen_metin, len(aday_parcalar))


def remote_llm_cevap_al(prompt, max_tokens=40):
    payload = {
        "model": REMOTE_LLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0,
        "max_tokens": max_tokens
    }

    request = urllib.request.Request(
        REMOTE_LLM_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=REMOTE_LLM_TIMEOUT
        ) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        hata_mesaji = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"remote_llm_http_error: {e.code} {hata_mesaji}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"remote_llm_connection_error: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise RuntimeError("remote_llm_timeout") from e

    try:
        data = json.loads(response_body)
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        raise RuntimeError(
            f"remote_llm_invalid_response: {response_body[:500]}"
        ) from e


def ders_notu_chunklerine_bol(transcript_parcalari, max_chars=4500):
    chunkler = []
    aktif_chunk = []
    aktif_uzunluk = 0

    for parca in transcript_parcalari:
        metin = (parca.get("text") or "").strip()

        if not metin:
            continue

        chapter = parca.get("chapter") or "Chapter bilgisi yok"
        start = parca.get("start", 0)
        end = parca.get("end", start)
        satir = f"[{start:.1f}-{end:.1f}] Chapter: {chapter} | {metin}"

        if aktif_chunk and aktif_uzunluk + len(satir) > max_chars:
            chunkler.append("\n".join(aktif_chunk))
            aktif_chunk = []
            aktif_uzunluk = 0

        aktif_chunk.append(satir)
        aktif_uzunluk += len(satir)

    if aktif_chunk:
        chunkler.append("\n".join(aktif_chunk))

    return chunkler


def llm_ile_ders_notu_parcasi_olustur(chunk_metni, video_basligi, bolum_no, toplam_bolum):
    prompt = f"""
Video başlığı:
{video_basligi or "Bilinmeyen video"}

Bu transcript parçası videonun {bolum_no}/{toplam_bolum} bölümüdür.

Görev:
Bu transcript parçasından öğrencinin sınava çalışırken anlayabileceği kısa ve düzenli ara ders notu çıkar.

Kurallar:
- Gereksiz konuşmaları, sponsor/reklam, abone ol, beğen, yorum yap ve link yönlendirme kısımlarını alma.
- Tanımlar, temel kavramlar, örnekler, önemli uyarılar ve işlem adımlarını vurgula.
- Çok uzun yazma; sadece bu parçadaki eğitim içeriğini özetle.
- Cevabı Türkçe yaz.

Transcript:
{chunk_metni}

Ara ders notu:
"""

    return remote_llm_cevap_al(
        prompt=prompt,
        max_tokens=450
    ).strip()


def llm_ile_ara_notlari_kisalt(ara_notlar, video_basligi):
    prompt = f"""
Video başlığı:
{video_basligi or "Bilinmeyen video"}

Aşağıdaki ara ders notlarını daha kısa, tekrarları azaltılmış ve düzenli bir ara özet haline getir.
Eğitim içeriğini koru; sponsor, reklam, abone ol gibi gereksiz kısımları alma.
Cevabı Türkçe yaz.

Ara notlar:
{chr(10).join(ara_notlar)}

Kısa ara özet:
"""

    return remote_llm_cevap_al(
        prompt=prompt,
        max_tokens=700
    ).strip()


def ara_notlari_sinirla(ara_notlar, video_basligi, max_chars=12000):
    aktif_notlar = [not_metni for not_metni in ara_notlar if not_metni.strip()]

    while len("\n".join(aktif_notlar)) > max_chars and len(aktif_notlar) > 1:
        yeni_notlar = []

        for index in range(0, len(aktif_notlar), 6):
            grup = aktif_notlar[index:index + 6]
            yeni_notlar.append(
                llm_ile_ara_notlari_kisalt(
                    grup,
                    video_basligi=video_basligi
                )
            )

        aktif_notlar = yeni_notlar

    return aktif_notlar


def llm_ile_final_ders_notu_olustur(ara_notlar, video_basligi):
    sinirli_notlar = ara_notlari_sinirla(
        ara_notlar,
        video_basligi=video_basligi
    )

    prompt = f"""
Video başlığı:
{video_basligi or "Bilinmeyen video"}

Aşağıdaki ara notları kullanarak öğrencinin sınava çalışırken hızlıca anlayabileceği kısa, düzenli ve başlıklı bir ders notu oluştur.

İstenen format:
# Ders Notu
## Konu Özeti
## Temel Kavramlar
## Önemli Noktalar
## Örnekler
## Sınav İçin Dikkat Edilecekler

Kurallar:
- Gereksiz konuşmaları, sponsor/reklam, abone ol, beğen, yorum yap ve link yönlendirme kısımlarını alma.
- Tanımlar, temel kavramlar, örnekler ve önemli uyarıları vurgula.
- Kısa, anlaşılır ve öğrenci dostu yaz.
- Cevabı Türkçe yaz.

Ara notlar:
{chr(10).join(sinirli_notlar)}

Final ders notu:
"""

    return remote_llm_cevap_al(
        prompt=prompt,
        max_tokens=1200
    ).strip()


def llm_ile_ders_notu_olustur(transcript_parcalari, video_basligi=""):
    chunkler = ders_notu_chunklerine_bol(transcript_parcalari)

    if len(chunkler) == 0:
        return ""

    print(f"Ders notu icin transcript chunk sayisi: {len(chunkler)}")

    ara_notlar = []

    for index, chunk_metni in enumerate(chunkler, start=1):
        print(f"Ders notu chunk isleniyor: {index}/{len(chunkler)}")
        ara_not = llm_ile_ders_notu_parcasi_olustur(
            chunk_metni=chunk_metni,
            video_basligi=video_basligi,
            bolum_no=index,
            toplam_bolum=len(chunkler)
        )

        if ara_not:
            ara_notlar.append(ara_not)

    if len(ara_notlar) == 0:
        return ""

    return llm_ile_final_ders_notu_olustur(
        ara_notlar,
        video_basligi=video_basligi
    )


def json_blogunu_ayikla(metin):
    metin = (metin or "").strip()

    if metin.startswith("```"):
        metin = re.sub(r"^```(?:json)?", "", metin, flags=re.IGNORECASE).strip()
        metin = re.sub(r"```$", "", metin).strip()

    baslangic = metin.find("{")
    bitis = metin.rfind("}")

    if baslangic == -1 or bitis == -1 or bitis <= baslangic:
        raise RuntimeError(f"quiz_json_bulunamadi: {metin[:300]}")

    return metin[baslangic:bitis + 1]


def quiz_sorularini_dogrula(data):
    sorular = data.get("sorular") if isinstance(data, dict) else None

    if sorular is None and isinstance(data, list):
        sorular = data

    if not isinstance(sorular, list):
        raise RuntimeError("quiz_json_sorular_listesi_yok")

    temiz_sorular = []

    for soru in sorular:
        if not isinstance(soru, dict):
            continue

        secenekler = soru.get("secenekler")
        if not isinstance(secenekler, dict):
            secenekler = {}

        soru_metni = str(
            soru.get("soru_metni")
            or soru.get("soru")
            or soru.get("question")
            or ""
        ).strip()
        secenek_a = str(
            soru.get("secenek_a")
            or secenekler.get("A")
            or secenekler.get("a")
            or ""
        ).strip()
        secenek_b = str(
            soru.get("secenek_b")
            or secenekler.get("B")
            or secenekler.get("b")
            or ""
        ).strip()
        secenek_c = str(
            soru.get("secenek_c")
            or secenekler.get("C")
            or secenekler.get("c")
            or ""
        ).strip()
        dogru_cevap_ham = str(
            soru.get("dogru_cevap")
            or soru.get("cevap")
            or soru.get("answer")
            or ""
        ).strip().upper()
        dogru_cevap_eslesme = re.search(r"[ABC]", dogru_cevap_ham)
        dogru_cevap = dogru_cevap_eslesme.group(0) if dogru_cevap_eslesme else ""
        aciklama = str(
            soru.get("aciklama")
            or soru.get("açıklama")
            or soru.get("explanation")
            or ""
        ).strip()

        if dogru_cevap not in ("A", "B", "C"):
            continue

        if not soru_metni or not secenek_a or not secenek_b or not secenek_c:
            continue

        temiz_sorular.append({
            "soru_metni": soru_metni[:1000],
            "secenek_a": secenek_a[:500],
            "secenek_b": secenek_b[:500],
            "secenek_c": secenek_c[:500],
            "dogru_cevap": dogru_cevap,
            "aciklama": aciklama[:1000]
        })

    if len(temiz_sorular) < 3:
        raise RuntimeError(f"quiz_soru_sayisi_gecersiz: {len(temiz_sorular)}")

    return temiz_sorular[:3]


def llm_ile_mini_quiz_olustur(kaynak_metni, video_basligi=""):
    son_hata = None

    for deneme in range(1, 4):
        kaynak_limit = 9000 if deneme == 1 else 6000
        prompt = f"""
Video başlığı:
{video_basligi or "Bilinmeyen video"}

Aşağıdaki ders notu / transcript özeti üzerinden öğrencinin videoyu anlayıp anlamadığını ölçen 3 adet mini quiz sorusu üret.

Kurallar:
- Sorular video içeriğindeki eğitim konularına dayanmalı.
- Sponsor, reklam, intro, outro, abone ol veya beğen bölümlerinden soru üretme.
- Her soruda tam 3 seçenek olsun: A, B, C.
- Sadece 1 doğru cevap olsun.
- Doğru cevabı sadece A, B veya C olarak yaz.
- Her soru için kısa açıklama yaz.
- Sorular öğrenci seviyesine uygun, anlaşılır ve alakalı olsun.
- Açıklamalar en fazla 1 kısa cümle olsun.
- Cevabı sadece geçerli JSON olarak ver. Açıklama, markdown veya kod bloğu ekleme.

Zorunlu JSON formatı:
{{
  "sorular": [
    {{
      "soru_metni": "...",
      "secenek_a": "...",
      "secenek_b": "...",
      "secenek_c": "...",
      "dogru_cevap": "A",
      "aciklama": "..."
    }},
    {{
      "soru_metni": "...",
      "secenek_a": "...",
      "secenek_b": "...",
      "secenek_c": "...",
      "dogru_cevap": "B",
      "aciklama": "..."
    }},
    {{
      "soru_metni": "...",
      "secenek_a": "...",
      "secenek_b": "...",
      "secenek_c": "...",
      "dogru_cevap": "C",
      "aciklama": "..."
    }}
  ]
}}

Kaynak metin:
{kaynak_metni[:kaynak_limit]}

JSON:
"""

        uretilen_metin = remote_llm_cevap_al(
            prompt=prompt,
            max_tokens=1800
        )
        print(f"Quiz LLM ham cevap deneme {deneme}:", uretilen_metin[:1200])

        try:
            data = json.loads(json_blogunu_ayikla(uretilen_metin))
            return quiz_sorularini_dogrula(data)
        except (RuntimeError, json.JSONDecodeError) as e:
            son_hata = e
            print(f"Quiz parse/dogrulama hatasi deneme {deneme}:", str(e))

    raise RuntimeError(f"quiz_uretim_basarisiz: {son_hata}")


def llm_indexlerini_parse_et(uretilen_metin, max_index):
    baslangic = uretilen_metin.find("[")

    if baslangic == -1:
        return []

    bitis = uretilen_metin.find("]", baslangic)

    if bitis == -1:
        liste_ici = uretilen_metin[baslangic + 1:]
    else:
        liste_ici = uretilen_metin[baslangic + 1:bitis]

    secilen_indexler = []

    for token in liste_ici.split(","):
        token = token.strip()

        if not re.fullmatch(r"\d+", token):
            continue

        index = int(token)

        if 1 <= index <= max_index and index not in secilen_indexler:
            secilen_indexler.append(index)

    return secilen_indexler[:6]


def llm_ile_atlanacak_kisimlari_bul(
    aday_parcalar,
    video_basligi="",
    video_aciklamasi="",
    video_ozeti=""
):
    tum_atlanacak_kisimlar = []

    if len(aday_parcalar) == 0:
        print("Atlanabilir LLM adayi yok. LLM istegi gonderilmedi.")
        return []

    chunkler = transcript_chunklere_bol(
        aday_parcalar,
        chunk_size=20
    )

    print(f"Toplam atlanabilir aday sayisi: {len(aday_parcalar)}")
    print(f"Toplam analiz edilecek atlanabilir aday chunk sayisi: {len(chunkler)}")

    for chunk_index, chunk in enumerate(chunkler):
        print(f"Atlanabilir aday chunk analiz ediliyor: {chunk_index + 1}")

        secilen_indexler = llm_ile_index_sec(
            chunk,
            video_basligi=video_basligi,
            video_aciklamasi=video_aciklamasi,
            video_ozeti=video_ozeti
        )
        print("LLM sectigi indexler:", secilen_indexler)

        for index in secilen_indexler:
            gercek_index = index - 1

            if 0 <= gercek_index < len(chunk):
                parca = chunk[gercek_index]
                aday_skoru = float(parca.get("skip_score", parca.get("score", 0.0)))
                final_skor = min(1.0, aday_skoru * 0.70 + 0.90 * 0.30)

                tum_atlanacak_kisimlar.append({
                    "text": parca["text"],
                    "start": parca["start"],
                    "end": parca["end"],
                    "skip_score": round(final_skor, 2),
                    "score": round(final_skor, 2),
                    "reason": parca.get("reason", "llm skippable"),
                    "chapter": parca.get("chapter"),
                    "heatmap_score": parca.get("heatmap_score", 0.0),
                    "source": "llm+rules+skippable"
                })

    return tum_atlanacak_kisimlar


def llm_ile_onemli_kisimlari_bul(
    aday_parcalar,
    video_basligi="",
    video_aciklamasi="",
    video_ozeti=""
):
    return llm_ile_atlanacak_kisimlari_bul(
        aday_parcalar,
        video_basligi=video_basligi,
        video_aciklamasi=video_aciklamasi,
        video_ozeti=video_ozeti
    )
