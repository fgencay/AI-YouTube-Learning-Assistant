from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from youtube_transcript_api import YouTubeTranscriptApi
from database import SessionLocal
from sqlalchemy import text
import json
from llm_service import (
    llm_ile_atlanacak_kisimlari_bul,
    llm_ile_ders_notu_olustur,
    llm_ile_mini_quiz_olustur
)
import yt_dlp
from pydantic import BaseModel
from typing import List, Optional
from urllib.parse import parse_qs, urlparse
import hashlib
import hmac
import os
import random
import re
import time
import urllib.error
import urllib.request

heatmap_cache = {}
analysis_locks = set()
skippable_cache_videos = set()
failed_login_attempts = {}


def heatmap_durumunu_getir(video_id):
    kayit = heatmap_cache.get(video_id)

    if kayit is None:
        return "missing", []

    if isinstance(kayit, list):
        durum = "available" if len(kayit) > 0 else "unavailable"
        return durum, kayit

    durum = kayit.get("status", "missing")
    segmentler = kayit.get("segments", [])

    return durum, segmentler

app = FastAPI(title="AI Video Asistanı API")

app.add_middleware(
    
    CORSMiddleware,
    allow_origins=[
        "https://www.youtube.com",
        "http://127.0.0.1:8000",
        "http://localhost:8000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class HeatmapItem(BaseModel):
    start: float
    end: float
    heat_score: float


class HeatmapRequest(BaseModel):
    heatmap: List[HeatmapItem]
    heatmap_unavailable: bool = False


class KayitRequest(BaseModel):
    ad: str
    email: str
    sifre: str


class GirisRequest(BaseModel):
    email: str
    sifre: str


class MobilAnalizRequest(BaseModel):
    kullanici_id: int
    youtube_url: str


PASSWORD_ITERATIONS = 120000
LOGIN_DELAY_STEP_SECONDS = 5


def email_normalize(email):
    return (email or "").strip().lower()


def basarisiz_giris_beklet(email):
    anahtar = email_normalize(email) or "unknown"
    kayit = failed_login_attempts.get(anahtar, {})

    if isinstance(kayit, int):
        kayit = {"attempts": kayit, "blocked_until": 0}

    deneme_sayisi = int(kayit.get("attempts", 0)) + 1
    bekleme_suresi = LOGIN_DELAY_STEP_SECONDS * deneme_sayisi
    failed_login_attempts[anahtar] = {
        "attempts": deneme_sayisi,
        "blocked_until": time.time() + bekleme_suresi
    }

    return deneme_sayisi, bekleme_suresi


def giris_bekleme_suresi_getir(email):
    kayit = failed_login_attempts.get(email_normalize(email))

    if not isinstance(kayit, dict):
        return 0

    kalan_sure = float(kayit.get("blocked_until", 0)) - time.time()

    if kalan_sure <= 0:
        return 0

    return int(kalan_sure + 0.999)


def basarili_giris_sayacini_sifirla(email):
    failed_login_attempts.pop(email_normalize(email), None)


def sifre_hash_olustur(sifre):
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        sifre.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS
    ).hex()

    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"


def sifre_dogrula(sifre, kayitli_hash):
    if not sifre or not kayitli_hash:
        return False

    parcalar = kayitli_hash.split("$")

    if len(parcalar) != 4 or parcalar[0] != "pbkdf2_sha256":
        return False

    try:
        iterations = int(parcalar[1])
    except ValueError:
        return False

    salt = parcalar[2]
    beklenen_digest = parcalar[3]
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        sifre.encode("utf-8"),
        salt.encode("utf-8"),
        iterations
    ).hex()

    return hmac.compare_digest(digest, beklenen_digest)


def youtube_video_id_cikar(youtube_url):
    deger = (youtube_url or "").strip()

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", deger):
        return deger

    parsed = urlparse(deger)
    host = parsed.netloc.lower()

    if "youtube.com" in host:
        query = parse_qs(parsed.query)

        if query.get("v") and re.fullmatch(r"[A-Za-z0-9_-]{11}", query["v"][0]):
            return query["v"][0]

        path_parts = [part for part in parsed.path.split("/") if part]

        if len(path_parts) >= 2 and path_parts[0] in ("shorts", "embed", "live"):
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", path_parts[1]):
                return path_parts[1]

    if "youtu.be" in host:
        path_parts = [part for part in parsed.path.split("/") if part]

        if path_parts and re.fullmatch(r"[A-Za-z0-9_-]{11}", path_parts[0]):
            return path_parts[0]

    eslesme = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", deger)

    if eslesme:
        return eslesme.group(1)

    return None


def youtube_id_gibi_mi(deger):
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", (deger or "").strip()))


def baslik_gecersiz_mi(baslik, youtube_video_id=None):
    temiz_baslik = (baslik or "").strip()

    if not temiz_baslik:
        return True

    if temiz_baslik.lower() in ("başlık alınamadı", "başlık yok", "baslik yok"):
        return True

    if youtube_video_id and temiz_baslik == youtube_video_id:
        return True

    return youtube_id_gibi_mi(temiz_baslik)


def baslik_gorunum_degeri(baslik, youtube_video_id=None):
    if baslik_gecersiz_mi(baslik, youtube_video_id):
        return "Başlık alınamadı"

    return baslik.strip()


def tarih_to_iso(tarih):
    if tarih is None:
        return None

    if hasattr(tarih, "isoformat"):
        return tarih.isoformat()

    return str(tarih)


def kisa_aciklama_olustur(video_aciklamasi="", video_ozeti="", video_basligi=""):
    kaynak = video_aciklamasi or video_ozeti or video_basligi or ""
    kaynak = " ".join(kaynak.replace("\n", " ").split())

    return kaynak[:1000]


def metni_karakter_limitine_kirpar(metin, limit):
    temiz_metin = " ".join((metin or "").replace("\n", " ").split())

    if not limit or limit < 1:
        return temiz_metin

    if len(temiz_metin) <= limit:
        return temiz_metin

    if limit <= 3:
        return temiz_metin[:limit]

    return temiz_metin[:limit - 3].rstrip() + "..."


@app.get("/")
def read_root():
    return {
        "mesaj": "🤖 Backend sunucusu tıkır tıkır çalışıyor!"
    }


@app.get("/db-test")
def db_test():
    try:
        db = SessionLocal()
        result = db.execute(text("SELECT DB_NAME()")).fetchone()
        db.close()

        return {
            "durum": "basarili",
            "veritabani": result[0]
        }

    except Exception as e:
        return {
            "durum": "hata",
            "mesaj": str(e)
        }


def onemli_kisimlari_bul(transcript):
    anahtar_kelimeler = [
        "important", "summary", "conclusion", "remember", "note", "critical",
        "finally", "key point", "main idea", "in short",
        "özet", "önemli", "sonuç", "dikkat", "unutmayın",
        "ana fikir", "kısaca", "son olarak", "kritik"
    ]

    gecilebilir_kelimeler = [
        "sponsor", "sponsored", "reklam", "subscribe", "like",
        "kanala abone", "videoyu beğen", "link in the description"
    ]

    skorlanmis_parcalar = []

    for parca in transcript:
        metin = parca["text"]
        metin_kucuk = metin.lower()

        skor = 0.0

        for kelime in anahtar_kelimeler:
            if kelime in metin_kucuk:
                skor += 0.45

        for kelime in gecilebilir_kelimeler:
            if kelime in metin_kucuk:
                skor -= 0.50

        kelime_sayisi = len(metin.split())

        if kelime_sayisi >= 8:
            skor += 0.20

        if kelime_sayisi >= 15:
            skor += 0.15

        if parca["start"] < 30:
            skor -= 0.10

        skor = max(0.0, min(1.0, skor))

        skorlanmis_parcalar.append({
            "text": metin,
            "start": parca["start"],
            "end": parca["start"] + parca["duration"],
            "score": round(skor, 2)
        })

    onemli_kisimlar = [
        parca for parca in skorlanmis_parcalar
        if parca["score"] >= 0.35
    ]

    if len(onemli_kisimlar) == 0:
        onemli_kisimlar = sorted(
            skorlanmis_parcalar,
            key=lambda x: x["score"],
            reverse=True
        )[:5]

    onemli_kisimlar = sorted(
        onemli_kisimlar,
        key=lambda x: x["start"]
    )

    return onemli_kisimlar[:15]


def video_ozeti_olustur(transcript):
    cumleler = []

    for parca in transcript[:15]:
        metin = parca["text"]

        if len(metin.split()) > 5:
            cumleler.append(metin)

    ozet = " ".join(cumleler)

    return ozet[:1000]


def transcript_temizle(transcript):
    temiz_liste = []

    for parca in transcript:
        metin = parca["text"].replace("\n", " ").strip()

        if len(metin) < 3:
            continue

        temiz_liste.append({
            "start": parca["start"],
            "end": parca["start"] + parca["duration"],
            "text": metin
        })

    return temiz_liste


TEKNIK_KELIMELER = [
    "variable", "variables", "data type", "string", "number", "input",
    "calculator", "list", "tuple", "function", "return", "if statement",
    "dictionary", "while", "for loop", "class", "object", "inheritance",
    "module", "pip", "file", "try", "except", "python", "code", "program",
    "algorithm", "database", "api", "backend", "frontend", "model",
    "prompt", "token", "json", "sql", "fastapi"
]

TEKNIK_CHAPTER_KELIMELERI = [
    "variables", "data types", "strings", "numbers", "input",
    "calculator", "lists", "tuples", "functions", "return",
    "if statements", "dictionaries", "while loop", "for loops",
    "classes", "objects", "inheritance", "modules", "pip",
    "files", "try", "except", "python", "code", "program",
    "api", "database", "model", "backend", "frontend"
]

DUSUK_ONEMLI_CHAPTER_KELIMELERI = [
    "introduction", "intro", "setup", "installing",
    "giris", "giri\u015f", "kurulum", "tanitim", "tan\u0131t\u0131m"
]

YASAKLI_KELIMELER = [
    "abone", "begen", "beÄŸen", "like", "subscribe", "sponsor",
    "sponsored", "reklam", "yorum yap", "kanala", "description",
    "aciklama", "aÃ§Ä±klama", "linke tikla", "linke tÄ±kla"
]

YASAKLI_KELIMELER.extend([
    "be\u011fen",
    "a\u00e7\u0131klama",
    "linke t\u0131kla"
])


GUCLU_SKIP_KELIMELERI = [
    "sponsor", "sponsored", "reklam", "ad break", "advertisement",
    "abone ol", "subscribe", "kanala abone", "begenmeyi unutma",
    "be\u011fenmeyi unutma", "videoyu begen", "videoyu be\u011fen",
    "like at", "like atin", "yorum yap", "comment below",
    "bildirim", "notification", "zile bas", "bell icon",
    "aciklamadaki link", "a\u00e7\u0131klamadaki link",
    "aciklama kismindaki link", "a\u00e7\u0131klama k\u0131sm\u0131ndaki link",
    "link aciklamada", "link a\u00e7\u0131klamada", "description link",
    "urun tanitimi", "\u00fcr\u00fcn tan\u0131t\u0131m\u0131"
]

ZAYIF_SKIP_KELIMELERI = [
    "intro", "outro", "giris muzigi", "giri\u015f m\u00fczi\u011fi",
    "muzik", "m\u00fczik", "music", "hos geldiniz",
    "ho\u015f geldiniz", "merhaba arkadaslar", "selam arkadaslar",
    "gorusmek uzere", "g\u00f6r\u00fc\u015fmek \u00fczere",
    "kendinize iyi bakin", "kanalima hos geldiniz",
    "kanal\u0131ma ho\u015f geldiniz"
]

SKIP_CHAPTER_KELIMELERI = [
    "sponsor", "sponsored", "reklam", "advertisement",
    "intro", "outro", "kapanis", "kapan\u0131\u015f"
]

EGITIM_KELIMELERI = [
    "tanim", "tan\u0131m", "ornek", "\u00f6rnek", "kod", "code",
    "formul", "form\u00fcl", "ders", "lesson", "aciklama",
    "a\u00e7\u0131klama", "neden", "nasil", "nas\u0131l", "fonksiyon",
    "function", "degisken", "de\u011fi\u015fken", "variable",
    "kurulum", "setup", "install", "python", "api", "database",
    "veritabani", "veritaban\u0131", "algoritma", "algorithm",
    "class", "object", "liste", "list", "dongu", "d\u00f6ng\u00fc",
    "if", "else", "return", "parametre", "method", "metot"
]


def kelime_var_mi(metin, kelimeler):
    return any(kelime in metin for kelime in kelimeler)


def egitim_icerigi_mi(metin):
    return kelime_var_mi(metin.lower(), EGITIM_KELIMELERI)


def guclu_skip_sinyali_var(metin, chapter_title=None):
    metin_kucuk = metin.lower()
    chapter_kucuk = (chapter_title or "").lower()

    return (
        kelime_var_mi(metin_kucuk, GUCLU_SKIP_KELIMELERI)
        or kelime_var_mi(chapter_kucuk, SKIP_CHAPTER_KELIMELERI)
    )


def skip_nedenleri_bul(metin, chapter_title=None, start=0, video_suresi=None):
    metin_kucuk = metin.lower()
    chapter_kucuk = (chapter_title or "").lower()
    nedenler = []

    if kelime_var_mi(metin_kucuk, [
        "sponsor", "sponsored", "reklam", "ad break",
        "advertisement", "urun tanitimi", "\u00fcr\u00fcn tan\u0131t\u0131m\u0131"
    ]):
        nedenler.append("sponsor/reklam")

    if kelime_var_mi(metin_kucuk, [
        "abone ol", "subscribe", "kanala abone",
        "begenmeyi unutma", "be\u011fenmeyi unutma",
        "videoyu begen", "videoyu be\u011fen", "like at",
        "like atin", "yorum yap", "bildirim", "zile bas"
    ]):
        nedenler.append("abonelik/etkilesim")

    if kelime_var_mi(metin_kucuk, [
        "aciklamadaki link", "a\u00e7\u0131klamadaki link",
        "aciklama kismindaki link", "a\u00e7\u0131klama k\u0131sm\u0131ndaki link",
        "link aciklamada", "link a\u00e7\u0131klamada", "description link"
    ]):
        nedenler.append("link yonlendirme")

    erken_bolum = float(start) < 90
    gec_bolum = video_suresi is not None and float(start) > max(0.0, float(video_suresi) - 120)

    if kelime_var_mi(chapter_kucuk, SKIP_CHAPTER_KELIMELERI):
        nedenler.append("skip chapter")

    if (erken_bolum or gec_bolum or kelime_var_mi(chapter_kucuk, SKIP_CHAPTER_KELIMELERI)) and kelime_var_mi(
        metin_kucuk,
        ZAYIF_SKIP_KELIMELERI
    ):
        nedenler.append("intro/outro")

    return nedenler


def skor_sinirla(skor):
    return max(0.0, min(1.0, skor))


def chapter_basligi_bul(parca, chapters):
    parca_start = parca["start"]

    for chapter in chapters:
        chapter_start = chapter.get("start")
        chapter_end = chapter.get("end")

        if chapter_start is None:
            continue

        if chapter_end is None:
            if parca_start >= chapter_start:
                return chapter.get("title")
        elif chapter_start <= parca_start <= chapter_end:
            return chapter.get("title")

    return None


def heatmap_ile_skor_guncelle(transcript_parcalari, heatmap_segments):
    guncellenmis_parcalar = []

    for parca in transcript_parcalari:
        en_yuksek_heat_score = 0.0

        for heatmap in heatmap_segments:
            heatmap_start = heatmap.get("start")
            heatmap_end = heatmap.get("end")
            heat_score = heatmap.get("heat_score", 0.0)

            if heatmap_start is None or heatmap_end is None:
                continue

            if parca["start"] <= heatmap_end and parca["end"] >= heatmap_start:
                en_yuksek_heat_score = max(en_yuksek_heat_score, float(heat_score))

        yeni_parca = dict(parca)
        yeni_parca["heatmap_score"] = round(en_yuksek_heat_score, 2)
        yeni_skor = float(yeni_parca.get("score", 0.0)) + en_yuksek_heat_score * 0.30

        if len(heatmap_segments) > 0 and en_yuksek_heat_score == 0.0:
            yeni_skor -= 0.10

        yeni_parca["score"] = skor_sinirla(yeni_skor)
        guncellenmis_parcalar.append(yeni_parca)

    return guncellenmis_parcalar


def adaylari_zamana_yay(skorlanmis_parcalar, aday_sayisi=30, min_aralik=60):
    skora_gore = sorted(
        skorlanmis_parcalar,
        key=lambda x: x["score"],
        reverse=True
    )

    secilenler = []

    for parca in skora_gore:
        if len(secilenler) >= aday_sayisi:
            break

        if all(abs(parca["start"] - secilen["start"]) >= min_aralik for secilen in secilenler):
            secilenler.append(parca)

    if len(secilenler) < aday_sayisi:
        for parca in skora_gore:
            if len(secilenler) >= aday_sayisi:
                break

            if parca not in secilenler:
                secilenler.append(parca)

    return secilenler


def zaman_araliklari_cakisiyor(a_start, a_end, b_start, b_end):
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return False

    return a_start <= b_end and a_end >= b_start


def chapter_icindeki_en_iyi_aday(skorlanmis_parcalar, chapter):
    chapter_start = chapter.get("start")
    chapter_end = chapter.get("end")

    if chapter_start is None or chapter_end is None:
        return None

    chapter_adaylari = [
        parca for parca in skorlanmis_parcalar
        if chapter_start <= parca["start"] <= chapter_end
    ]

    if len(chapter_adaylari) == 0:
        return None

    return sorted(
        chapter_adaylari,
        key=lambda x: x["score"],
        reverse=True
    )[0]


def chapter_adaylarini_garanti_et(secilen_adaylar, skorlanmis_parcalar, chapters):
    if len(chapters) == 0:
        return secilen_adaylar

    sonuc = list(secilen_adaylar)

    for chapter in chapters:
        chapter_start = chapter.get("start")
        chapter_end = chapter.get("end")

        if chapter_start is None or chapter_end is None:
            continue

        temsil_ediliyor = any(
            chapter_start <= aday["start"] <= chapter_end
            for aday in sonuc
        )

        if temsil_ediliyor:
            continue

        en_iyi_aday = chapter_icindeki_en_iyi_aday(
            skorlanmis_parcalar,
            chapter
        )

        if en_iyi_aday and en_iyi_aday not in sonuc:
            sonuc.append(en_iyi_aday)

    return sorted(
        sonuc,
        key=lambda x: x["score"],
        reverse=True
    )


def transcript_adaylarini_sec(transcript, chapters, heatmap_segments, aday_sayisi=30):
    skorlanmis_parcalar = []

    for parca in transcript:
        metin = parca["text"].strip()
        metin_kucuk = metin.lower()
        kelime_sayisi = len(metin.split())
        sure = parca["end"] - parca["start"]

        if kelime_sayisi < 4 or sure < 2:
            continue

        if any(kelime in metin_kucuk for kelime in YASAKLI_KELIMELER):
            continue

        skor = 0.10

        if kelime_sayisi >= 8:
            skor += 0.15

        if kelime_sayisi >= 15:
            skor += 0.10

        if any(kelime in metin_kucuk for kelime in TEKNIK_KELIMELER):
            skor += 0.20

        chapter_title = chapter_basligi_bul(parca, chapters)

        if chapter_title:
            chapter_lower = chapter_title.lower()

            if any(kelime in chapter_lower for kelime in TEKNIK_CHAPTER_KELIMELERI):
                skor += 0.15

            if any(kelime in chapter_lower for kelime in DUSUK_ONEMLI_CHAPTER_KELIMELERI):
                skor -= 0.30

        if parca["start"] < 30:
            skor -= 0.30
        elif parca["start"] < 60:
            skor -= 0.15

        skorlanmis_parcalar.append({
            "text": metin,
            "start": parca["start"],
            "end": parca["end"],
            "score": skor_sinirla(skor),
            "chapter": chapter_title,
            "heatmap_score": 0.0,
            "source": "candidate+chapter+heatmap"
        })

    skorlanmis_parcalar = heatmap_ile_skor_guncelle(
        skorlanmis_parcalar,
        heatmap_segments
    )

    secilen_adaylar = adaylari_zamana_yay(
        skorlanmis_parcalar,
        aday_sayisi=aday_sayisi,
        min_aralik=60
    )

    return chapter_adaylarini_garanti_et(
        secilen_adaylar,
        skorlanmis_parcalar,
        chapters
    )


def heatmap_skoru_bul(parca, heatmap_segments):
    en_yuksek_heat_score = 0.0

    for heatmap in heatmap_segments:
        heatmap_start = heatmap.get("start")
        heatmap_end = heatmap.get("end")
        heat_score = heatmap.get("heat_score", 0.0)

        if heatmap_start is None or heatmap_end is None:
            continue

        if parca["start"] <= heatmap_end and parca["end"] >= heatmap_start:
            en_yuksek_heat_score = max(en_yuksek_heat_score, float(heat_score))

    return round(en_yuksek_heat_score, 2)


def atlanacak_adaylarini_sec(transcript, chapters, heatmap_segments, aday_sayisi=30):
    skorlanmis_parcalar = []
    video_suresi = video_suresini_bul(transcript)

    for parca in transcript:
        metin = parca["text"].strip()
        metin_kucuk = metin.lower()
        kelime_sayisi = len(metin.split())
        sure = float(parca["end"]) - float(parca["start"])

        if sure < 1.0:
            continue

        chapter_title = chapter_basligi_bul(parca, chapters)
        nedenler = skip_nedenleri_bul(
            metin=metin,
            chapter_title=chapter_title,
            start=parca["start"],
            video_suresi=video_suresi
        )
        egitim_sinyali = egitim_icerigi_mi(metin)
        heatmap_score = heatmap_skoru_bul(parca, heatmap_segments)

        skor = 0.0

        if len(nedenler) > 0:
            skor += 0.55

        if guclu_skip_sinyali_var(metin, chapter_title):
            skor += 0.20

        if kelime_var_mi((chapter_title or "").lower(), SKIP_CHAPTER_KELIMELERI):
            skor += 0.15

        if parca["start"] < 60 and kelime_var_mi(metin_kucuk, ZAYIF_SKIP_KELIMELERI):
            skor += 0.15

        if video_suresi and parca["start"] > max(0.0, video_suresi - 90) and kelime_var_mi(
            metin_kucuk,
            ZAYIF_SKIP_KELIMELERI
        ):
            skor += 0.15

        if kelime_sayisi <= 3 and len(nedenler) == 0:
            continue

        if egitim_sinyali and not guclu_skip_sinyali_var(metin, chapter_title):
            skor -= 0.60
        elif egitim_sinyali:
            skor -= 0.20

        if heatmap_score > 0:
            if len(nedenler) > 0:
                skor += heatmap_score * 0.08
            elif heatmap_score >= 0.65:
                skor -= heatmap_score * 0.10

        skor = skor_sinirla(skor)

        if skor < 0.35:
            continue

        skorlanmis_parcalar.append({
            "text": metin,
            "start": parca["start"],
            "end": parca["end"],
            "skip_score": round(skor, 2),
            "score": round(skor, 2),
            "reason": ", ".join(nedenler) if len(nedenler) > 0 else "kural tabanli skip adayi",
            "chapter": chapter_title,
            "heatmap_score": heatmap_score,
            "education_signal": egitim_sinyali,
            "source": "rules+skippable"
        })

    secilen_adaylar = sorted(
        skorlanmis_parcalar,
        key=lambda x: x["skip_score"],
        reverse=True
    )[:aday_sayisi]

    return sorted(
        secilen_adaylar,
        key=lambda x: x["start"]
    )


def guvenli_atlanacak_kisimlari_temizle(atlanacak_kisimlar):
    temiz_liste = []

    for parca in atlanacak_kisimlar:
        metin = parca["text"].strip()
        sure = float(parca["end"]) - float(parca["start"])
        skip_score = float(parca.get("skip_score", parca.get("score", 0.0)))
        guclu_skip = guclu_skip_sinyali_var(metin, parca.get("chapter"))
        egitim_sinyali = egitim_icerigi_mi(metin)

        if sure < 1.0:
            continue

        if skip_score < 0.35:
            continue

        if egitim_sinyali and not guclu_skip:
            continue

        temiz = dict(parca)
        temiz["skip_score"] = round(skip_score, 2)
        temiz["score"] = round(skip_score, 2)
        temiz["reason"] = temiz.get("reason") or "guvenli skip sinyali"
        temiz_liste.append(temiz)

    return temiz_liste


def rule_based_atlanacak_fallback(aday_parcalar, limit=10):
    guvenli_adaylar = [
        parca for parca in aday_parcalar
        if guclu_skip_sinyali_var(parca["text"], parca.get("chapter"))
        or "intro/outro" in parca.get("reason", "")
    ]

    guvenli_adaylar = sorted(
        guvenli_adaylar,
        key=lambda x: x.get("skip_score", x.get("score", 0.0)),
        reverse=True
    )[:limit]

    sonuc = []

    for parca in guvenli_adaylar:
        skor = float(parca.get("skip_score", parca.get("score", 0.0)))
        sonuc.append({
            "text": parca["text"],
            "start": parca["start"],
            "end": parca["end"],
            "skip_score": round(skor, 2),
            "score": round(skor, 2),
            "reason": parca.get("reason", "rule based skip"),
            "chapter": parca.get("chapter"),
            "heatmap_score": parca.get("heatmap_score", 0.0),
            "source": "rules+fallback+skippable"
        })

    return sonuc


def transcript_prompta_hazirla(temiz_transcript, limit=40):
    secilenler = temiz_transcript[:limit]

    metin_bloklari = []

    for index, parca in enumerate(secilenler, start=1):
        metin_bloklari.append(
            f"{index}. [{round(parca['start'], 2)} - {round(parca['end'], 2)}] {parca['text']}"
        )

    return "\n".join(metin_bloklari)


def llm_prompt_olustur(temiz_transcript):
    transcript_metni = transcript_prompta_hazirla(temiz_transcript)

    prompt = f"""
Sen bir yapay zeka destekli video içerik analiz sistemisin.

Görevin:
Aşağıdaki YouTube video transcript parçalarını analiz et.
Eğitim açısından önemli, bilgi içeren, konu anlatımı yapan ve kullanıcının mutlaka izlemesi gereken bölümleri seç.

Şunları önemli kabul et:
- Kavram açıklamaları
- Tanımlar
- Örnek anlatımlar
- Sonuç ve özet cümleleri
- Kodlama / teknik açıklamalar
- Konunun ana fikrini veren bölümler

Şunları önemsiz kabul et:
- Selamlama
- Abone ol / beğen / yorum yap çağrıları
- Sponsor / reklam bölümleri
- Tekrar eden cümleler
- Boş veya anlamsız ifadeler

Cevabı sadece JSON formatında ver:

[
  {{
    "start": 12.5,
    "end": 20.3,
    "text": "seçilen transcript metni",
    "importance_score": 0.87,
    "reason": "Bu bölüm temel kavramı açıklıyor."
  }}
]

Transcript:
{transcript_metni}
"""

    return prompt


def youtube_oembed_bilgisi_cek(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        request = urllib.request.Request(
            f"https://www.youtube.com/oembed?url={url}&format=json",
            headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        return {
            "title": data.get("title"),
            "description": "",
            "chapters": []
        }

    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as e:
        print("oEmbed başlık çekme hatası:", str(e))
        return {
            "title": None,
            "description": "",
            "chapters": []
        }


def youtube_video_bilgisi_cek(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": False
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        chapters = info.get("chapters", [])

        temiz_chapters = []

        for chapter in chapters:
            temiz_chapters.append({
                "title": chapter.get("title"),
                "start": chapter.get("start_time"),
                "end": chapter.get("end_time")
            })

        title = info.get("title")

        if baslik_gecersiz_mi(title, video_id):
            oembed_bilgisi = youtube_oembed_bilgisi_cek(video_id)
            title = oembed_bilgisi.get("title")

        return {
            "title": None if baslik_gecersiz_mi(title, video_id) else title,
            "description": info.get("description") or "",
            "chapters": temiz_chapters
        }

    except Exception as e:
        print("Chapter çekme hatası:", str(e))
        oembed_bilgisi = youtube_oembed_bilgisi_cek(video_id)

        if not baslik_gecersiz_mi(oembed_bilgisi.get("title"), video_id):
            return oembed_bilgisi

        return {
            "title": None,
            "description": "",
            "chapters": []
        }


def youtube_chapter_bilgisi_cek(video_id):
    return youtube_video_bilgisi_cek(video_id)["chapters"]


def db_video_var_mi(db, youtube_video_id):
    sorgu = text("""
        SELECT video_id, youtube_video_id, dil, transcript, baslik, video_url
        FROM Videolar
        WHERE youtube_video_id = :youtube_video_id
    """)

    return db.execute(
        sorgu,
        {"youtube_video_id": youtube_video_id}
    ).fetchone()


def db_video_id_ile_getir(db, video_id):
    sorgu = text("""
        SELECT video_id, youtube_video_id, dil, transcript, baslik, video_url
        FROM Videolar
        WHERE video_id = :video_id
    """)

    return db.execute(
        sorgu,
        {"video_id": video_id}
    ).fetchone()


def db_ders_notu_getir(db, video_id):
    sorgu = text("""
        SELECT ders_notu_id, video_id, ders_notu, model_adi, olusturma_tarihi
        FROM VideoDersNotlari
        WHERE video_id = :video_id
    """)

    satir = db.execute(
        sorgu,
        {"video_id": video_id}
    ).fetchone()

    if not satir:
        return None

    return {
        "ders_notu_id": satir[0],
        "video_id": satir[1],
        "ders_notu": satir[2],
        "model_adi": satir[3],
        "olusturma_tarihi": tarih_to_iso(satir[4])
    }


def db_ders_notu_kaydet(db, video_id, ders_notu, model_adi):
    sorgu = text("""
        INSERT INTO VideoDersNotlari (video_id, ders_notu, model_adi, olusturma_tarihi)
        OUTPUT INSERTED.ders_notu_id, INSERTED.olusturma_tarihi
        VALUES (:video_id, :ders_notu, :model_adi, GETDATE())
    """)

    satir = db.execute(
        sorgu,
        {
            "video_id": video_id,
            "ders_notu": ders_notu,
            "model_adi": model_adi
        }
    ).fetchone()

    return {
        "ders_notu_id": satir[0],
        "video_id": video_id,
        "ders_notu": ders_notu,
        "model_adi": model_adi,
        "olusturma_tarihi": tarih_to_iso(satir[1])
    }


def db_quiz_sorularini_getir(db, video_id):
    sorgu = text("""
        SELECT TOP 3
            quiz_soru_id,
            video_id,
            soru_metni,
            secenek_a,
            secenek_b,
            secenek_c,
            dogru_cevap,
            aciklama,
            model_adi,
            olusturma_tarihi
        FROM VideoQuizSorulari
        WHERE video_id = :video_id
        ORDER BY quiz_soru_id ASC
    """)

    sonuc = db.execute(
        sorgu,
        {"video_id": video_id}
    ).fetchall()

    sorular = []

    for satir in sonuc:
        sorular.append({
            "quiz_soru_id": satir[0],
            "video_id": satir[1],
            "soru_metni": satir[2],
            "secenekler": {
                "A": satir[3],
                "B": satir[4],
                "C": satir[5]
            },
            "secenek_a": satir[3],
            "secenek_b": satir[4],
            "secenek_c": satir[5],
            "dogru_cevap": satir[6],
            "aciklama": satir[7],
            "model_adi": satir[8],
            "olusturma_tarihi": tarih_to_iso(satir[9])
        })

    return sorular


def db_quiz_sorularini_sil(db, video_id):
    sorgu = text("""
        DELETE FROM VideoQuizSorulari
        WHERE video_id = :video_id
    """)

    db.execute(sorgu, {"video_id": video_id})


def db_quiz_sorularini_kaydet(db, video_id, sorular, model_adi):
    sorgu = text("""
        INSERT INTO VideoQuizSorulari
        (
            video_id,
            soru_metni,
            secenek_a,
            secenek_b,
            secenek_c,
            dogru_cevap,
            aciklama,
            model_adi,
            olusturma_tarihi
        )
        OUTPUT INSERTED.quiz_soru_id, INSERTED.olusturma_tarihi
        VALUES
        (
            :video_id,
            :soru_metni,
            :secenek_a,
            :secenek_b,
            :secenek_c,
            :dogru_cevap,
            :aciklama,
            :model_adi,
            GETDATE()
        )
    """)

    kayitlar = []

    for soru in sorular:
        satir = db.execute(
            sorgu,
            {
                "video_id": video_id,
                "soru_metni": soru["soru_metni"],
                "secenek_a": soru["secenek_a"],
                "secenek_b": soru["secenek_b"],
                "secenek_c": soru["secenek_c"],
                "dogru_cevap": soru["dogru_cevap"],
                "aciklama": soru.get("aciklama", ""),
                "model_adi": model_adi
            }
        ).fetchone()

        kayitlar.append({
            "quiz_soru_id": satir[0],
            "video_id": video_id,
            "soru_metni": soru["soru_metni"],
            "secenekler": {
                "A": soru["secenek_a"],
                "B": soru["secenek_b"],
                "C": soru["secenek_c"]
            },
            "secenek_a": soru["secenek_a"],
            "secenek_b": soru["secenek_b"],
            "secenek_c": soru["secenek_c"],
            "dogru_cevap": soru["dogru_cevap"],
            "aciklama": soru.get("aciklama", ""),
            "model_adi": model_adi,
            "olusturma_tarihi": tarih_to_iso(satir[1])
        })

    return kayitlar


def quiz_cevap_dagilimi_zayif_mi(sorular):
    cevaplar = [
        (soru.get("dogru_cevap") or "").upper()
        for soru in sorular[:3]
        if soru.get("dogru_cevap")
    ]

    return len(cevaplar) >= 3 and len(set(cevaplar)) < 3


def quiz_sorularinin_seceneklerini_karistir(sorular):
    hedef_cevaplar = ["A", "B", "C"]
    random.shuffle(hedef_cevaplar)
    sonuc = []

    for index, soru in enumerate(sorular[:3]):
        eski_dogru_cevap = (soru.get("dogru_cevap") or "").upper()
        secenekler = {
            "A": soru.get("secenek_a", ""),
            "B": soru.get("secenek_b", ""),
            "C": soru.get("secenek_c", "")
        }

        if eski_dogru_cevap not in secenekler:
            sonuc.append(soru)
            continue

        dogru_metin = secenekler[eski_dogru_cevap]
        yanlis_metinler = [
            metin
            for harf, metin in secenekler.items()
            if harf != eski_dogru_cevap
        ]
        random.shuffle(yanlis_metinler)

        yeni_dogru_cevap = hedef_cevaplar[index % len(hedef_cevaplar)]
        yeni_secenekler = {yeni_dogru_cevap: dogru_metin}
        yanlis_harfler = [
            harf for harf in ["A", "B", "C"]
            if harf != yeni_dogru_cevap
        ]

        for harf, metin in zip(yanlis_harfler, yanlis_metinler):
            yeni_secenekler[harf] = metin

        yeni_soru = dict(soru)
        yeni_soru["secenek_a"] = yeni_secenekler.get("A", "")
        yeni_soru["secenek_b"] = yeni_secenekler.get("B", "")
        yeni_soru["secenek_c"] = yeni_secenekler.get("C", "")
        yeni_soru["dogru_cevap"] = yeni_dogru_cevap
        sonuc.append(yeni_soru)

    return sonuc


def db_quiz_sorularini_dengele(db, video_id, sorular):
    model_adi = (
        sorular[0].get("model_adi")
        if sorular and sorular[0].get("model_adi")
        else os.getenv("REMOTE_LLM_MODEL", "qwen2.5-14b-local-fp16")
    )
    dengeli_sorular = quiz_sorularinin_seceneklerini_karistir(sorular)

    db_quiz_sorularini_sil(db, video_id)
    return db_quiz_sorularini_kaydet(
        db=db,
        video_id=video_id,
        sorular=dengeli_sorular,
        model_adi=model_adi
    )


def transcript_json_coz(transcript):
    if not transcript:
        return []

    if isinstance(transcript, list):
        return transcript

    try:
        return json.loads(transcript)
    except (TypeError, json.JSONDecodeError):
        return []


def ders_notu_transcriptini_hazirla(ham_veri, chapters):
    temiz_transcript = transcript_temizle(ham_veri)
    hazir_transcript = []

    for parca in temiz_transcript:
        yeni_parca = dict(parca)
        yeni_parca["chapter"] = chapter_basligi_bul(parca, chapters)
        hazir_transcript.append(yeni_parca)

    return hazir_transcript


def db_zaman_damgalarini_getir(db, video_id):
    sorgu = text("""
        SELECT baslangic_saniye, bitis_saniye, metin, onem_skoru
        FROM OzetZamanDamgalari
        WHERE video_id = :video_id
        ORDER BY baslangic_saniye ASC
    """)

    sonuc = db.execute(
        sorgu,
        {"video_id": video_id}
    ).fetchall()

    zamanlar = []

    for satir in sonuc:
        zamanlar.append({
            "start": satir[0],
            "end": satir[1],
            "text": satir[2],
            "skip_score": satir[3],
            "score": satir[3],
            "chapter": None,
            "source": "cache",
            "heatmap_score": 0.0,
            "reason": "cache"
        })

    return zamanlar


def db_video_kaydet(db, youtube_video_id, dil, transcript, baslik=None, video_url=None):
    guvenli_baslik = baslik_gorunum_degeri(baslik, youtube_video_id)
    sorgu = text("""
        INSERT INTO Videolar (youtube_video_id, dil, transcript, baslik, video_url)
        OUTPUT INSERTED.video_id
        VALUES (:youtube_video_id, :dil, :transcript, :baslik, :video_url)
    """)

    yeni_video_id = db.execute(
        sorgu,
        {
            "youtube_video_id": youtube_video_id,
            "dil": dil,
            "transcript": json.dumps(transcript, ensure_ascii=False),
            "baslik": guvenli_baslik,
            "video_url": video_url
        }
    ).fetchone()[0]

    return yeni_video_id


def db_video_baslik_guncelle(db, video_id, baslik):
    if baslik_gecersiz_mi(baslik):
        return

    sorgu = text("""
        UPDATE Videolar
        SET baslik = :baslik
        WHERE video_id = :video_id
    """)

    db.execute(
        sorgu,
        {
            "video_id": video_id,
            "baslik": baslik
        }
    )


def video_basligini_yeniden_cek(youtube_video_id):
    if not youtube_video_id:
        return None

    video_bilgisi = youtube_video_bilgisi_cek(youtube_video_id)
    baslik = video_bilgisi.get("title")

    if baslik_gecersiz_mi(baslik, youtube_video_id):
        return None

    return baslik


def db_video_basligini_onar_gerekirse(db, video_id, youtube_video_id, mevcut_baslik):
    if not baslik_gecersiz_mi(mevcut_baslik, youtube_video_id):
        return mevcut_baslik

    yeni_baslik = video_basligini_yeniden_cek(youtube_video_id)

    if yeni_baslik:
        db_video_baslik_guncelle(db, video_id, yeni_baslik)
        return yeni_baslik

    return None


def db_video_url_guncelle(db, video_id, video_url):
    if not video_url:
        return

    sorgu = text("""
        UPDATE Videolar
        SET video_url = :video_url
        WHERE video_id = :video_id
    """)

    db.execute(
        sorgu,
        {
            "video_id": video_id,
            "video_url": video_url
        }
    )


def db_kullanici_email_ile_bul(db, email):
    sorgu = text("""
        SELECT kullanici_id, ad, email, sifre_hash
        FROM Kullanicilar
        WHERE email = :email
    """)

    return db.execute(
        sorgu,
        {"email": email}
    ).fetchone()


def db_kullanici_id_ile_bul(db, kullanici_id):
    sorgu = text("""
        SELECT kullanici_id, ad, email
        FROM Kullanicilar
        WHERE kullanici_id = :kullanici_id
    """)

    return db.execute(
        sorgu,
        {"kullanici_id": kullanici_id}
    ).fetchone()


def db_kullanici_kaydet(db, ad, email, sifre_hash):
    sorgu = text("""
        INSERT INTO Kullanicilar (ad, email, olusturma_tarihi, sifre_hash)
        OUTPUT INSERTED.kullanici_id
        VALUES (:ad, :email, GETDATE(), :sifre_hash)
    """)

    return db.execute(
        sorgu,
        {
            "ad": ad,
            "email": email,
            "sifre_hash": sifre_hash
        }
    ).fetchone()[0]


def db_kullanici_analiz_kaydet_veya_guncelle(db, kullanici_id, video_id, kisa_aciklama):
    kolon_sorgu = text("""
        SELECT
            COALESCE(
                CHARACTER_MAXIMUM_LENGTH,
                CASE
                    WHEN COL_LENGTH('dbo.KullaniciAnalizleri', 'kisa_aciklama') > 0
                    THEN COL_LENGTH('dbo.KullaniciAnalizleri', 'kisa_aciklama') / 2
                    ELSE 100
                END
            )
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME = 'KullaniciAnalizleri'
          AND COLUMN_NAME = 'kisa_aciklama'
    """)
    kolon = db.execute(kolon_sorgu).fetchone()
    karakter_limiti = kolon[0] if kolon and kolon[0] and kolon[0] > 0 else 1000
    karakter_limiti = max(1, min(int(karakter_limiti), 1000))
    guvenli_kisa_aciklama = metni_karakter_limitine_kirpar(
        kisa_aciklama,
        karakter_limiti
    )

    mevcut_sorgu = text("""
        SELECT TOP 1 analiz_id
        FROM KullaniciAnalizleri
        WHERE kullanici_id = :kullanici_id
          AND video_id = :video_id
        ORDER BY analiz_tarihi DESC
    """)

    mevcut = db.execute(
        mevcut_sorgu,
        {
            "kullanici_id": kullanici_id,
            "video_id": video_id
        }
    ).fetchone()

    if mevcut:
        guncelle_sorgu = text("""
            UPDATE KullaniciAnalizleri
            SET kisa_aciklama = LEFT(:kisa_aciklama, :karakter_limiti),
                analiz_tarihi = GETDATE()
            WHERE analiz_id = :analiz_id
        """)

        db.execute(
            guncelle_sorgu,
            {
                "analiz_id": mevcut[0],
                "kisa_aciklama": guvenli_kisa_aciklama,
                "karakter_limiti": karakter_limiti
            }
        )

        return mevcut[0]

    ekle_sorgu = text("""
        INSERT INTO KullaniciAnalizleri (kullanici_id, video_id, kisa_aciklama, analiz_tarihi)
        OUTPUT INSERTED.analiz_id
        VALUES (:kullanici_id, :video_id, LEFT(:kisa_aciklama, :karakter_limiti), GETDATE())
    """)

    return db.execute(
        ekle_sorgu,
        {
            "kullanici_id": kullanici_id,
            "video_id": video_id,
            "kisa_aciklama": guvenli_kisa_aciklama,
            "karakter_limiti": karakter_limiti
        }
    ).fetchone()[0]


def db_kullanici_analizlerini_getir(db, kullanici_id):
    sorgu = text("""
        SELECT
            ka.analiz_id,
            v.video_id,
            v.youtube_video_id,
            v.video_url,
            v.baslik,
            ka.kisa_aciklama,
            ka.analiz_tarihi,
            v.dil
        FROM KullaniciAnalizleri ka
        INNER JOIN Videolar v ON v.video_id = ka.video_id
        WHERE ka.kullanici_id = :kullanici_id
        ORDER BY ka.analiz_tarihi DESC
    """)

    sonuc = db.execute(
        sorgu,
        {"kullanici_id": kullanici_id}
    ).fetchall()

    analizler = []

    for satir in sonuc:
        baslik = db_video_basligini_onar_gerekirse(
            db=db,
            video_id=satir[1],
            youtube_video_id=satir[2],
            mevcut_baslik=satir[4]
        )

        analizler.append({
            "analiz_id": satir[0],
            "video_id": satir[1],
            "youtube_video_id": satir[2],
            "video_url": satir[3],
            "baslik": baslik_gorunum_degeri(baslik, satir[2]),
            "kisa_aciklama": satir[5] or "",
            "analiz_tarihi": tarih_to_iso(satir[6]),
            "dil": satir[7]
        })

    return analizler


def db_kullanici_video_detayini_getir(db, kullanici_id, video_id):
    sorgu = text("""
        SELECT TOP 1
            ka.analiz_id,
            v.video_id,
            v.youtube_video_id,
            v.video_url,
            v.baslik,
            ka.kisa_aciklama,
            ka.analiz_tarihi,
            v.dil
        FROM KullaniciAnalizleri ka
        INNER JOIN Videolar v ON v.video_id = ka.video_id
        WHERE ka.kullanici_id = :kullanici_id
          AND v.video_id = :video_id
    """)

    satir = db.execute(
        sorgu,
        {
            "kullanici_id": kullanici_id,
            "video_id": video_id
        }
    ).fetchone()

    if not satir:
        return None

    baslik = db_video_basligini_onar_gerekirse(
        db=db,
        video_id=satir[1],
        youtube_video_id=satir[2],
        mevcut_baslik=satir[4]
    )

    return {
        "analiz_id": satir[0],
        "video_id": satir[1],
        "youtube_video_id": satir[2],
        "video_url": satir[3],
        "baslik": baslik_gorunum_degeri(baslik, satir[2]),
        "kisa_aciklama": satir[5] or "",
        "analiz_tarihi": tarih_to_iso(satir[6]),
        "dil": satir[7]
    }


def chapter_ile_skor_guncelle(onemli_kisimlar, chapters):
    teknik_chapter_kelimeleri = [
        "variables", "data types", "strings", "numbers", "input",
        "calculator", "lists", "tuples", "functions", "return",
        "if statements", "dictionaries", "while loop", "for loops",
        "classes", "objects", "inheritance", "modules", "pip",
        "files", "try", "except", "python", "code", "program"
    ]

    dusuk_onemli_chapter_kelimeleri = [
        "introduction", "intro", "setup", "installing"
    ]

    guncellenmis_kisimlar = []

    for parca in onemli_kisimlar:
        parca_start = parca["start"]
        chapter_title = None

        for chapter in chapters:
            if chapter["start"] is not None and chapter["end"] is not None:
                if chapter["start"] <= parca_start <= chapter["end"]:
                    chapter_title = chapter["title"]
                    break

        yeni_skor = parca["score"]

        if chapter_title:
            chapter_title_lower = chapter_title.lower()

            for kelime in teknik_chapter_kelimeleri:
                if kelime in chapter_title_lower:
                    yeni_skor += 0.10
                    break

            for kelime in dusuk_onemli_chapter_kelimeleri:
                if kelime in chapter_title_lower:
                    yeni_skor -= 0.10
                    break

        yeni_skor = max(0.0, min(1.0, yeni_skor))

        guncellenmis_kisimlar.append({
            "text": parca["text"],
            "start": parca["start"],
            "end": parca["end"],
            "score": round(yeni_skor, 2),
            "chapter": chapter_title
        })

    return guncellenmis_kisimlar

def gereksiz_kisimlari_temizle(onemli_kisimlar):
    yasakli_kelimeler = [
        "abone", "beğen", "like", "subscribe", "sponsor",
        "reklam", "yorum yap", "kanala", "description",
        "açıklama kısmı", "linke tıkla"
    ]

    temiz_liste = []

    for parca in onemli_kisimlar:
        metin = parca["text"].strip()
        metin_kucuk = metin.lower()

        kelime_sayisi = len(metin.split())

        # Çok kısa parçaları alma
        if kelime_sayisi < 4:
            continue

        # Yasaklı kelime varsa alma
        if any(kelime in metin_kucuk for kelime in yasakli_kelimeler):
            continue

        # Süresi çok kısa ise alma
        sure = parca["end"] - parca["start"]
        if sure < 2:
            continue

        temiz_liste.append(parca)

    return temiz_liste

def yakin_kisimlari_birlestir(onemli_kisimlar, max_bosluk=3):
    if len(onemli_kisimlar) == 0:
        return []

    birlesmis = []

    aktif = onemli_kisimlar[0]

    for sonraki in onemli_kisimlar[1:]:

        bosluk = sonraki["start"] - aktif["end"]

        # Eğer aradaki boşluk küçükse birleştir
        if bosluk <= max_bosluk:

            aktif["end"] = sonraki["end"]

            aktif["text"] += " " + sonraki["text"]

            aktif["score"] = round(
                max(aktif["score"], sonraki["score"]),
                2
            )

            aktif["skip_score"] = round(
                max(
                    float(aktif.get("skip_score", aktif.get("score", 0.0))),
                    float(sonraki.get("skip_score", sonraki.get("score", 0.0)))
                ),
                2
            )

            aktif["heatmap_score"] = round(
                max(
                    float(aktif.get("heatmap_score", 0.0)),
                    float(sonraki.get("heatmap_score", 0.0))
                ),
                2
            )

            if not aktif.get("chapter") and sonraki.get("chapter"):
                aktif["chapter"] = sonraki.get("chapter")

            aktif["source"] = aktif.get("source") or sonraki.get("source") or "llm+chapter+heatmap"

            if sonraki.get("reason") and sonraki.get("reason") not in aktif.get("reason", ""):
                aktif["reason"] = (
                    f"{aktif.get('reason', '').strip()}, {sonraki.get('reason')}"
                ).strip(", ")

        else:
            birlesmis.append(aktif)
            aktif = sonraki

    birlesmis.append(aktif)

    return birlesmis


def video_suresini_bul(transcript):
    if len(transcript) == 0:
        return None

    son_parca = transcript[-1]

    if "duration" in son_parca:
        return son_parca["start"] + son_parca["duration"]

    return son_parca.get("end")


def konusmasiz_intro_segmentlerini_uret(
    transcript,
    chapters,
    heatmap_segments,
    min_sessizlik=5.0,
    max_intro_suresi=60.0
):
    if len(transcript) == 0:
        return []

    ilk_parca = min(transcript, key=lambda parca: parca["start"])
    ilk_konusma_start = float(ilk_parca["start"])

    if ilk_konusma_start <= min_sessizlik:
        return []

    bitis = min(ilk_konusma_start - 0.25, max_intro_suresi)

    if bitis <= 1.0:
        return []

    intro_parca = {
        "start": 0.0,
        "end": round(bitis, 2),
        "text": "Konusmasiz/muzikli intro"
    }
    chapter_title = chapter_basligi_bul(intro_parca, chapters)
    heatmap_score = heatmap_skoru_bul(intro_parca, heatmap_segments)

    skor = 0.88

    if kelime_var_mi((chapter_title or "").lower(), SKIP_CHAPTER_KELIMELERI):
        skor += 0.06

    if heatmap_score >= 0.75:
        skor -= 0.10
    elif heatmap_score > 0:
        skor += 0.03

    skor = skor_sinirla(skor)

    return [{
        "text": "Konusmasiz/muzikli intro",
        "start": 0.0,
        "end": round(bitis, 2),
        "skip_score": round(skor, 2),
        "score": round(skor, 2),
        "reason": "konusmasiz/muzikli intro",
        "chapter": chapter_title,
        "heatmap_score": heatmap_score,
        "source": "rules+silent_intro+skippable"
    }]


def cumle_sonu_mu(metin):
    metin = metin.strip().rstrip('"\' )]}')

    if len(metin) == 0:
        return False

    return metin.endswith((".", "?", "!", "\u2026"))


def transcript_indeksi_bul(transcript, zaman):
    if len(transcript) == 0:
        return None

    for index, parca in enumerate(transcript):
        if parca["start"] <= zaman <= parca["end"]:
            return index

        if parca["end"] >= zaman:
            return index

    return len(transcript) - 1


def cumle_baslangic_indeksi_bul(transcript, index, max_geri_sure=12):
    if index is None:
        return None

    aktif_index = index

    while aktif_index > 0:
        aktif = transcript[aktif_index]
        onceki = transcript[aktif_index - 1]
        bosluk = aktif["start"] - onceki["end"]

        if cumle_sonu_mu(onceki["text"]) or bosluk > 1.5:
            break

        if transcript[index]["start"] - onceki["start"] > max_geri_sure:
            break

        aktif_index -= 1

    return aktif_index


def cumle_bitis_indeksi_bul(transcript, index, max_ileri_sure=20):
    if index is None:
        return None

    aktif_index = index
    ilk_end = transcript[index]["end"]

    while aktif_index < len(transcript) - 1:
        aktif = transcript[aktif_index]

        if cumle_sonu_mu(aktif["text"]):
            break

        sonraki = transcript[aktif_index + 1]
        bosluk = sonraki["start"] - aktif["end"]

        if bosluk > 1.5:
            break

        if sonraki["end"] - ilk_end > max_ileri_sure:
            break

        aktif_index += 1

    return aktif_index


def segmentleri_cumle_sinirlarina_hizala(onemli_kisimlar, transcript, video_suresi=None):
    if len(onemli_kisimlar) == 0 or len(transcript) == 0:
        return onemli_kisimlar

    hizalanmis_segmentler = []

    for parca in onemli_kisimlar:
        start_index = transcript_indeksi_bul(transcript, float(parca["start"]))
        end_index = transcript_indeksi_bul(transcript, float(parca["end"]))

        start_index = cumle_baslangic_indeksi_bul(transcript, start_index)
        end_index = cumle_bitis_indeksi_bul(transcript, end_index)

        if start_index is None or end_index is None:
            hizalanmis_segmentler.append(parca)
            continue

        if end_index < start_index:
            end_index = start_index

        start = transcript[start_index]["start"]
        end = transcript[end_index]["end"] + 0.8

        if video_suresi is not None:
            end = min(float(video_suresi), end)

        yeni_parca = dict(parca)
        yeni_parca["start"] = round(start, 2)
        yeni_parca["end"] = round(max(end, start + 2), 2)
        yeni_parca["source"] = f"{yeni_parca.get('source', 'segment')}+sentence_boundary"
        hizalanmis_segmentler.append(yeni_parca)

    hizalanmis_segmentler = sorted(
        hizalanmis_segmentler,
        key=lambda x: x["start"]
    )

    return yakin_kisimlari_birlestir(
        hizalanmis_segmentler,
        max_bosluk=4
    )


def baglam_indekslerini_bul(
    transcript,
    start_index,
    end_index,
    onceki_parca_sayisi=2,
    sonraki_parca_sayisi=2,
    max_genisleme=25
):
    if start_index is None or end_index is None:
        return start_index, end_index

    if end_index < start_index:
        end_index = start_index

    for onceki_sayi, sonraki_sayi in [(2, 2), (1, 2), (2, 1), (1, 1), (0, 1), (1, 0), (0, 0)]:
        onceki_sayi = min(onceki_sayi, onceki_parca_sayisi)
        sonraki_sayi = min(sonraki_sayi, sonraki_parca_sayisi)

        context_start = max(0, start_index - onceki_sayi)
        context_end = min(len(transcript) - 1, end_index + sonraki_sayi)

        genisleme = (
            transcript[start_index]["start"] - transcript[context_start]["start"]
        ) + (
            transcript[context_end]["end"] - transcript[end_index]["end"]
        )

        if genisleme <= max_genisleme:
            return context_start, context_end

    return start_index, end_index


def segmentleri_transcript_baglami_ile_genislet(
    onemli_kisimlar,
    transcript,
    video_suresi=None,
    onceki_parca_sayisi=2,
    sonraki_parca_sayisi=2,
    padding_once=1.5,
    padding_sonra=2.5,
    max_genisleme=25,
    max_bosluk=0.75
):
    if len(onemli_kisimlar) == 0 or len(transcript) == 0:
        return onemli_kisimlar

    genisletilmis_segmentler = []

    for parca in onemli_kisimlar:
        start_index = transcript_indeksi_bul(transcript, float(parca["start"]))
        end_index = transcript_indeksi_bul(transcript, float(parca["end"]))

        context_start, context_end = baglam_indekslerini_bul(
            transcript=transcript,
            start_index=start_index,
            end_index=end_index,
            onceki_parca_sayisi=onceki_parca_sayisi,
            sonraki_parca_sayisi=sonraki_parca_sayisi,
            max_genisleme=max_genisleme
        )

        if context_start is None or context_end is None:
            genisletilmis_segmentler.append(parca)
            continue

        start = max(0.0, transcript[context_start]["start"] - padding_once)
        end = transcript[context_end]["end"] + padding_sonra

        if video_suresi is not None:
            end = min(float(video_suresi), end)

        yeni_parca = dict(parca)
        yeni_parca["start"] = round(start, 2)
        yeni_parca["end"] = round(max(end, start + 2), 2)
        yeni_parca["text"] = " ".join(
            transcript[index]["text"]
            for index in range(context_start, context_end + 1)
        )
        yeni_parca["source"] = f"{yeni_parca.get('source', 'segment')}+transcript_context"
        genisletilmis_segmentler.append(yeni_parca)

    genisletilmis_segmentler = sorted(
        genisletilmis_segmentler,
        key=lambda x: x["start"]
    )

    return yakin_kisimlari_birlestir(
        genisletilmis_segmentler,
        max_bosluk=max_bosluk
    )


def segmentleri_izlenebilir_hale_getir(
    onemli_kisimlar,
    video_suresi=None,
    oncesi=8,
    sonrasi=18,
    min_sure=35,
    max_bosluk=18
):
    izlenebilir_segmentler = []

    for parca in onemli_kisimlar:
        start = max(0.0, float(parca["start"]) - oncesi)
        end = float(parca["end"]) + sonrasi

        if video_suresi is not None:
            end = min(float(video_suresi), end)

        sure = end - start

        if sure < min_sure:
            eksik = min_sure - sure
            start = max(0.0, start - eksik / 2)
            end = end + eksik / 2

            if video_suresi is not None and end > video_suresi:
                tasma = end - video_suresi
                end = float(video_suresi)
                start = max(0.0, start - tasma)

        yeni_parca = dict(parca)
        yeni_parca["start"] = round(start, 2)
        yeni_parca["end"] = round(end, 2)
        yeni_parca["source"] = "llm+chapter+heatmap+context"
        izlenebilir_segmentler.append(yeni_parca)

    izlenebilir_segmentler = sorted(
        izlenebilir_segmentler,
        key=lambda x: x["start"]
    )

    return yakin_kisimlari_birlestir(
        izlenebilir_segmentler,
        max_bosluk=max_bosluk
    )


def final_segmentlerde_chapter_kapsamini_tamamla(onemli_kisimlar, aday_parcalar, chapters):
    if len(chapters) == 0:
        return onemli_kisimlar

    sonuc = list(onemli_kisimlar)

    for chapter in chapters:
        chapter_start = chapter.get("start")
        chapter_end = chapter.get("end")

        if chapter_start is None or chapter_end is None:
            continue

        temsil_ediliyor = any(
            zaman_araliklari_cakisiyor(
                parca["start"],
                parca["end"],
                chapter_start,
                chapter_end
            )
            for parca in sonuc
        )

        if temsil_ediliyor:
            continue

        en_iyi_aday = chapter_icindeki_en_iyi_aday(
            aday_parcalar,
            chapter
        )

        if not en_iyi_aday:
            continue

        tamamlayici = dict(en_iyi_aday)
        tamamlayici["score"] = round(
            min(1.0, float(tamamlayici.get("score", 0.0)) * 0.70 + 0.90 * 0.30),
            2
        )
        tamamlayici["source"] = "chapter_coverage+heatmap"
        sonuc.append(tamamlayici)

    return sorted(
        sonuc,
        key=lambda x: x["start"]
    )

def db_zaman_damgalarini_kaydet(db, video_id, onemli_kisimlar):
    sorgu = text("""
        INSERT INTO OzetZamanDamgalari
        (video_id, baslangic_saniye, bitis_saniye, metin, onem_skoru)
        VALUES
        (:video_id, :baslangic_saniye, :bitis_saniye, :metin, :onem_skoru)
    """)

    for parca in onemli_kisimlar:
        db.execute(
            sorgu,
            {
                "video_id": video_id,
                "baslangic_saniye": parca["start"],
                "bitis_saniye": parca["end"],
                "metin": parca["text"],
                "onem_skoru": parca.get("score", parca.get("skip_score", 0.0))
            }
        )


def db_zaman_damgalarini_sil(db, video_id):
    sorgu = text("""
        DELETE FROM OzetZamanDamgalari
        WHERE video_id = :video_id
    """)

    db.execute(sorgu, {"video_id": video_id})


@app.post("/api/kayit")
def kullanici_kayit(request: KayitRequest):
    db = SessionLocal()

    try:
        ad = (request.ad or "").strip()
        email = email_normalize(request.email)
        sifre = request.sifre or ""

        if len(ad) < 2:
            return {
                "durum": "hata",
                "mesaj": "Ad en az 2 karakter olmali."
            }

        if "@" not in email or "." not in email:
            return {
                "durum": "hata",
                "mesaj": "Gecerli bir email adresi girin."
            }

        if len(sifre) < 6:
            return {
                "durum": "hata",
                "mesaj": "Sifre en az 6 karakter olmali."
            }

        mevcut = db_kullanici_email_ile_bul(db, email)

        if mevcut:
            return {
                "durum": "hata",
                "mesaj": "Bu email adresi ile kayitli bir kullanici var."
            }

        sifre_hash = sifre_hash_olustur(sifre)
        kullanici_id = db_kullanici_kaydet(
            db=db,
            ad=ad,
            email=email,
            sifre_hash=sifre_hash
        )
        db.commit()

        return {
            "durum": "basarili",
            "kullanici_id": kullanici_id,
            "ad": ad,
            "email": email
        }

    except Exception as e:
        db.rollback()
        return {
            "durum": "hata",
            "mesaj": "Kayit sirasinda hata olustu.",
            "teknik_hata": str(e)
        }

    finally:
        db.close()


@app.post("/api/giris")
def kullanici_giris(request: GirisRequest):
    db = SessionLocal()

    try:
        email = email_normalize(request.email)
        sifre = request.sifre or ""

        aktif_bekleme = giris_bekleme_suresi_getir(email)

        if aktif_bekleme > 0:
            return {
                "durum": "hata",
                "mesaj": "E-mail veya şifre hatalı",
                "bekleme_suresi": aktif_bekleme,
                "giris_engelli": True
            }

        kullanici = db_kullanici_email_ile_bul(db, email)

        if not kullanici or not sifre_dogrula(sifre, kullanici[3]):
            deneme_sayisi, bekleme_suresi = basarisiz_giris_beklet(email)
            return {
                "durum": "hata",
                "mesaj": "E-mail veya şifre hatalı",
                "basarisiz_deneme_sayisi": deneme_sayisi,
                "bekleme_suresi": bekleme_suresi,
                "giris_engelli": True
            }

        basarili_giris_sayacini_sifirla(email)

        return {
            "durum": "basarili",
            "kullanici_id": kullanici[0],
            "ad": kullanici[1],
            "email": kullanici[2]
        }

    except Exception as e:
        return {
            "durum": "hata",
            "mesaj": "Giris sirasinda hata olustu.",
            "teknik_hata": str(e)
        }

    finally:
        db.close()


@app.post("/api/mobil/analiz")
def mobil_analiz(request: MobilAnalizRequest):
    video_id = youtube_video_id_cikar(request.youtube_url)

    if not video_id:
        return {
            "durum": "hata",
            "mesaj": "Gecerli bir YouTube linki veya video ID girin."
        }

    db = SessionLocal()

    try:
        kullanici = db_kullanici_id_ile_bul(db, request.kullanici_id)

        if not kullanici:
            return {
                "durum": "hata",
                "mesaj": "Kullanici bulunamadi."
            }

    finally:
        db.close()

    analiz_sonucu = metin_cek(video_id)

    if analiz_sonucu.get("durum") != "basarili":
        return analiz_sonucu

    db = SessionLocal()

    try:
        mevcut_video = db_video_var_mi(db, video_id)

        if not mevcut_video:
            return {
                "durum": "hata",
                "mesaj": "Analiz tamamlandi ancak video kaydi bulunamadi."
            }

        kisa_aciklama = kisa_aciklama_olustur(
            video_aciklamasi=analiz_sonucu.get("video_aciklamasi", ""),
            video_ozeti=analiz_sonucu.get("video_ozeti", ""),
            video_basligi=analiz_sonucu.get("video_basligi", "")
        )
        analiz_id = db_kullanici_analiz_kaydet_veya_guncelle(
            db=db,
            kullanici_id=request.kullanici_id,
            video_id=mevcut_video[0],
            kisa_aciklama=kisa_aciklama
        )
        db.commit()

        analiz_sonucu["analiz_id"] = analiz_id
        analiz_sonucu["kullanici_id"] = request.kullanici_id
        analiz_sonucu["kullanici_analizi_kaydedildi"] = True
        analiz_sonucu["kisa_aciklama"] = kisa_aciklama

        return analiz_sonucu

    except Exception as e:
        db.rollback()
        return {
            "durum": "hata",
            "mesaj": "Mobil analiz kaydi olusturulamadi.",
            "teknik_hata": str(e)
        }

    finally:
        db.close()


@app.get("/api/kullanicilar/{kullanici_id}/analizler")
def kullanici_analizleri(kullanici_id: int):
    db = SessionLocal()

    try:
        kullanici = db_kullanici_id_ile_bul(db, kullanici_id)

        if not kullanici:
            return {
                "durum": "hata",
                "mesaj": "Kullanici bulunamadi.",
                "analizler": []
            }

        analizler = db_kullanici_analizlerini_getir(db, kullanici_id)
        db.commit()

        return {
            "durum": "basarili",
            "kullanici_id": kullanici_id,
            "analiz_sayisi": len(analizler),
            "analizler": analizler
        }

    except Exception as e:
        return {
            "durum": "hata",
            "mesaj": "Analiz gecmisi alinamadi.",
            "teknik_hata": str(e),
            "analizler": []
        }

    finally:
        db.close()


@app.get("/api/kullanicilar/{kullanici_id}/analizler/{video_id}")
def kullanici_analiz_detayi(kullanici_id: int, video_id: int):
    db = SessionLocal()

    try:
        video = db_kullanici_video_detayini_getir(db, kullanici_id, video_id)

        if not video:
            return {
                "durum": "hata",
                "mesaj": "Video analizi bulunamadi."
            }

        segmentler = db_zaman_damgalarini_getir(db, video_id)
        db.commit()

        return {
            "durum": "basarili",
            "kullanici_id": kullanici_id,
            "video": video,
            "segment_sayisi": len(segmentler),
            "segmentler": segmentler
        }

    except Exception as e:
        return {
            "durum": "hata",
            "mesaj": "Video detayi alinamadi.",
            "teknik_hata": str(e)
        }

    finally:
        db.close()


@app.get("/api/videolar/{video_id}/ders-notu")
def video_ders_notu(video_id: int):
    db = SessionLocal()

    try:
        kayitli_not = db_ders_notu_getir(db, video_id)

        if kayitli_not:
            return {
                "durum": "basarili",
                "kaynak": "veritabani_cache",
                **kayitli_not
            }

        video = db_video_id_ile_getir(db, video_id)

        if not video:
            return {
                "durum": "hata",
                "mesaj": "Video bulunamadi."
            }

        ham_veri = transcript_json_coz(video[3])

        if len(ham_veri) == 0:
            return {
                "durum": "hata",
                "mesaj": "Bu video icin transcript bulunamadi."
            }

        youtube_video_id = video[1]
        video_basligi = video[4]
        video_bilgisi = youtube_video_bilgisi_cek(youtube_video_id)
        chapters = video_bilgisi.get("chapters", [])

        if baslik_gecersiz_mi(video_basligi, youtube_video_id) and video_bilgisi.get("title"):
            video_basligi = video_bilgisi["title"]

        video_basligi = baslik_gorunum_degeri(video_basligi, youtube_video_id)

        hazir_transcript = ders_notu_transcriptini_hazirla(
            ham_veri,
            chapters
        )

        if len(hazir_transcript) == 0:
            return {
                "durum": "hata",
                "mesaj": "Ders notu icin kullanilabilir transcript bulunamadi."
            }

        ders_notu = llm_ile_ders_notu_olustur(
            hazir_transcript,
            video_basligi=video_basligi
        )

        if not ders_notu:
            return {
                "durum": "hata",
                "mesaj": "Ders notu olusturulamadi."
            }

        kayit = db_ders_notu_kaydet(
            db=db,
            video_id=video_id,
            ders_notu=ders_notu,
            model_adi=os.getenv("REMOTE_LLM_MODEL", "qwen2.5-14b-local-fp16")
        )
        db.commit()

        return {
            "durum": "basarili",
            "kaynak": "llm_yeni_ders_notu",
            **kayit
        }

    except Exception as e:
        db.rollback()

        kayitli_not = db_ders_notu_getir(db, video_id)

        if kayitli_not:
            return {
                "durum": "basarili",
                "kaynak": "veritabani_cache",
                **kayitli_not
            }

        if "remote_llm_" in str(e):
            return {
                "durum": "hata",
                "mesaj": "RunPod LLM sunucusuna ulasilamadi veya ders notu uretilemedi.",
                "teknik_hata": str(e)
            }

        return {
            "durum": "hata",
            "mesaj": "Ders notu alinamadi.",
            "teknik_hata": str(e)
        }

    finally:
        db.close()


@app.get("/api/videolar/{video_id}/mini-quiz")
def video_mini_quiz(video_id: int):
    db = SessionLocal()

    try:
        kayitli_sorular = db_quiz_sorularini_getir(db, video_id)

        if len(kayitli_sorular) >= 3:
            if quiz_cevap_dagilimi_zayif_mi(kayitli_sorular):
                kayitli_sorular = db_quiz_sorularini_dengele(
                    db=db,
                    video_id=video_id,
                    sorular=kayitli_sorular
                )
                db.commit()

            return {
                "durum": "basarili",
                "kaynak": "veritabani_cache",
                "video_id": video_id,
                "soru_sayisi": 3,
                "sorular": kayitli_sorular[:3]
            }

        if 0 < len(kayitli_sorular) < 3:
            db_quiz_sorularini_sil(db, video_id)
            db.commit()

        video = db_video_id_ile_getir(db, video_id)

        if not video:
            return {
                "durum": "hata",
                "mesaj": "Video bulunamadi."
            }

        youtube_video_id = video[1]
        video_basligi = video[4]
        model_adi = os.getenv("REMOTE_LLM_MODEL", "qwen2.5-14b-local-fp16")

        kayitli_not = db_ders_notu_getir(db, video_id)

        if kayitli_not and kayitli_not.get("ders_notu"):
            kaynak_metni = kayitli_not["ders_notu"]
        else:
            ham_veri = transcript_json_coz(video[3])

            if len(ham_veri) == 0:
                return {
                    "durum": "hata",
                    "mesaj": "Bu video icin transcript bulunamadi."
                }

            video_bilgisi = youtube_video_bilgisi_cek(youtube_video_id)
            chapters = video_bilgisi.get("chapters", [])

            if baslik_gecersiz_mi(video_basligi, youtube_video_id) and video_bilgisi.get("title"):
                video_basligi = video_bilgisi["title"]

            video_basligi = baslik_gorunum_degeri(video_basligi, youtube_video_id)

            hazir_transcript = ders_notu_transcriptini_hazirla(
                ham_veri,
                chapters
            )

            if len(hazir_transcript) == 0:
                return {
                    "durum": "hata",
                    "mesaj": "Mini quiz icin kullanilabilir transcript bulunamadi."
                }

            kaynak_metni = llm_ile_ders_notu_olustur(
                hazir_transcript,
                video_basligi=video_basligi
            )

        video_basligi = baslik_gorunum_degeri(video_basligi, youtube_video_id)

        if not kaynak_metni:
            return {
                "durum": "hata",
                "mesaj": "Mini quiz icin kaynak metin olusturulamadi."
            }

        sorular = llm_ile_mini_quiz_olustur(
            kaynak_metni=kaynak_metni,
            video_basligi=video_basligi
        )
        sorular = quiz_sorularinin_seceneklerini_karistir(sorular)
        kayitlar = db_quiz_sorularini_kaydet(
            db=db,
            video_id=video_id,
            sorular=sorular,
            model_adi=model_adi
        )
        db.commit()

        return {
            "durum": "basarili",
            "kaynak": "llm_yeni_mini_quiz",
            "video_id": video_id,
            "soru_sayisi": len(kayitlar),
            "sorular": kayitlar
        }

    except Exception as e:
        db.rollback()
        print("Mini quiz hatasi:", str(e))

        kayitli_sorular = db_quiz_sorularini_getir(db, video_id)

        if len(kayitli_sorular) >= 3:
            return {
                "durum": "basarili",
                "kaynak": "veritabani_cache",
                "video_id": video_id,
                "soru_sayisi": 3,
                "sorular": kayitli_sorular[:3]
            }

        if "remote_llm_" in str(e):
            return {
                "durum": "hata",
                "mesaj": "RunPod LLM sunucusuna ulasilamadi veya mini quiz uretilemedi.",
                "teknik_hata": str(e)
            }

        return {
            "durum": "hata",
            "mesaj": "Mini quiz alinamadi.",
            "teknik_hata": str(e)
        }

    finally:
        db.close()


@app.get("/api/metin-cek/{video_id}")
def metin_cek(video_id: str, kullanici_id: Optional[int] = None):
    db = SessionLocal()
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        heatmap_durumu, heatmap_segments = heatmap_durumunu_getir(video_id)
        heatmap_kullanildi = heatmap_durumu == "available" and len(heatmap_segments) > 0
        mevcut_video = db_video_var_mi(db, video_id)

        if mevcut_video and not heatmap_kullanildi and video_id in skippable_cache_videos:
            kayitli_video_id = mevcut_video[0]
            kayitli_zamanlar = db_zaman_damgalarini_getir(db, kayitli_video_id)
            analiz_id = None

            if kullanici_id is not None:
                kisa_aciklama = kisa_aciklama_olustur(
                    video_basligi=baslik_gorunum_degeri(mevcut_video[4], video_id)
                )
                analiz_id = db_kullanici_analiz_kaydet_veya_guncelle(
                    db=db,
                    kullanici_id=kullanici_id,
                    video_id=kayitli_video_id,
                    kisa_aciklama=kisa_aciklama
                )
                db.commit()

            db.close()

            analiz_mesaji = (
                "Bu videoda guvenle atlanacak gereksiz bolum bulunmadi. Video normal oynayacak."
                if len(kayitli_zamanlar) == 0
                else f"{len(kayitli_zamanlar)} atlanacak bolum bulundu."
            )

            return {
                "durum": "basarili",
                "mesaj": analiz_mesaji,
                "kaynak": "veritabani_cache",
                "analiz_tipi": "skippable",
                "video_id": video_id,
                "video_basligi": baslik_gorunum_degeri(mevcut_video[4], video_id),
                "video_url": mevcut_video[5] or video_url,
                "video_aciklamasi": "",
                "video_ozeti": "",
                "dil": mevcut_video[2],
                "toplam_parca": 0,
                "chapter_sayisi": 0,
                "heatmap_segment_sayisi": 0,
                "heatmap_kullanildi": False,
                "heatmap_durumu": heatmap_durumu,
                "analiz_id": analiz_id,
                "kullanici_id": kullanici_id,
                "kullanici_analizi_kaydedildi": analiz_id is not None,
                "atlanacak_kisim_sayisi": len(kayitli_zamanlar),
                "atlanacak_kisimlar": kayitli_zamanlar,
                "onemli_kisim_sayisi": len(kayitli_zamanlar),
                "onemli_kisimlar": kayitli_zamanlar
            }

        if video_id in analysis_locks:
            db.close()
            return {
                "durum": "hata",
                "video_id": video_id,
                "mesaj": "Bu video icin analiz zaten devam ediyor. Biraz sonra tekrar deneyin.",
                "teknik_hata": "analysis_in_progress"
            }

        analysis_locks.add(video_id)

        kayitli_video_id = None

        if mevcut_video:
            kayitli_video_id = mevcut_video[0]
            ham_veri = json.loads(mevcut_video[3])
            dil = mevcut_video[2]
            kaynak = "skippable_yeniden_analiz" if heatmap_kullanildi else "skippable_yeniden_analiz_no_heatmap"
        else:
            ytt_api = YouTubeTranscriptApi()
            altyazi = ytt_api.fetch(video_id, languages=["tr", "en"])
            ham_veri = altyazi.to_raw_data()
            dil = altyazi.language_code
            kaynak = "youtube_yeni_skippable_analiz" if heatmap_kullanildi else "youtube_yeni_skippable_analiz_no_heatmap"

        video_bilgisi = youtube_video_bilgisi_cek(video_id)
        video_basligi = baslik_gorunum_degeri(video_bilgisi.get("title"), video_id)
        video_aciklamasi = video_bilgisi.get("description") or ""
        chapters = video_bilgisi.get("chapters", [])

        temiz_transcript = transcript_temizle(ham_veri)
        video_ozeti = video_ozeti_olustur(ham_veri)

        # 1. Önce LLM ile önemli kısımları bul
        atlanacak_adaylar = atlanacak_adaylarini_sec(
            transcript=temiz_transcript,
            chapters=chapters,
            heatmap_segments=heatmap_segments,
            aday_sayisi=30
        )

        atlanacak_kisimlar = llm_ile_atlanacak_kisimlari_bul(
            atlanacak_adaylar,
            video_basligi=video_basligi,
            video_aciklamasi=video_aciklamasi,
            video_ozeti=video_ozeti
        )

        # 2. LLM boş dönerse rule-based sisteme geç
        if len(atlanacak_kisimlar) == 0:
            atlanacak_kisimlar = rule_based_atlanacak_fallback(
                atlanacak_adaylar,
                limit=10
            )

        # 3. Chapter bilgisiyle skorları güncelle
        # 4. Gereksiz / kısa / reklam parçalarını temizle
        atlanacak_kisimlar = guvenli_atlanacak_kisimlari_temizle(atlanacak_kisimlar)

        atlanacak_kisimlar = sorted(atlanacak_kisimlar, key=lambda x: x["start"])
        atlanacak_kisimlar = segmentleri_transcript_baglami_ile_genislet(
            atlanacak_kisimlar,
            temiz_transcript,
            video_suresi=video_suresini_bul(ham_veri),
            onceki_parca_sayisi=0,
            sonraki_parca_sayisi=0,
            padding_once=0.0,
            padding_sonra=0.6,
            max_genisleme=5,
            max_bosluk=1.5
        )

        atlanacak_kisimlar.extend(
            konusmasiz_intro_segmentlerini_uret(
                transcript=temiz_transcript,
                chapters=chapters,
                heatmap_segments=heatmap_segments,
                min_sessizlik=5.0
            )
        )

        atlanacak_kisimlar = guvenli_atlanacak_kisimlari_temizle(atlanacak_kisimlar)
        atlanacak_kisimlar = yakin_kisimlari_birlestir(
            sorted(atlanacak_kisimlar, key=lambda x: x["start"]),
            max_bosluk=1.5
        )

        for parca in atlanacak_kisimlar:
            skip_score = float(parca.get("skip_score", parca.get("score", 0.0)))
            parca["skip_score"] = round(skip_score, 2)
            parca["score"] = round(skip_score, 2)
            parca["reason"] = parca.get("reason") or "skippable"
            if "silent_intro" in parca.get("source", ""):
                if heatmap_kullanildi:
                    parca["source"] = "rules+silent_intro+heatmap+skippable"
                else:
                    parca["source"] = "rules+silent_intro+no_heatmap+skippable"
            elif heatmap_kullanildi:
                parca["source"] = "llm+rules+heatmap+skippable"
            else:
                parca["source"] = "llm+rules+no_heatmap+skippable"
            parca["heatmap_score"] = parca.get("heatmap_score", 0.0)
            parca["chapter"] = parca.get("chapter")

        if kayitli_video_id is None:
            yeni_video_id = db_video_kaydet(
                db=db,
                youtube_video_id=video_id,
                dil=dil,
                transcript=ham_veri,
                baslik=video_basligi,
                video_url=video_url
            )
        else:
            yeni_video_id = kayitli_video_id
            db_video_baslik_guncelle(db, yeni_video_id, video_basligi)
            db_video_url_guncelle(db, yeni_video_id, video_url)
            db_zaman_damgalarini_sil(db, yeni_video_id)

        db_zaman_damgalarini_kaydet(
            db=db,
            video_id=yeni_video_id,
            onemli_kisimlar=atlanacak_kisimlar
        )

        analiz_id = None

        if kullanici_id is not None:
            kisa_aciklama = kisa_aciklama_olustur(
                video_aciklamasi=video_aciklamasi,
                video_ozeti=video_ozeti,
                video_basligi=video_basligi
            )
            analiz_id = db_kullanici_analiz_kaydet_veya_guncelle(
                db=db,
                kullanici_id=kullanici_id,
                video_id=yeni_video_id,
                kisa_aciklama=kisa_aciklama
            )

        db.commit()
        skippable_cache_videos.add(video_id)
        analysis_locks.discard(video_id)
        db.close()

        analiz_mesaji = (
            "Bu videoda guvenle atlanacak gereksiz bolum bulunmadi. Video normal oynayacak."
            if len(atlanacak_kisimlar) == 0
            else f"{len(atlanacak_kisimlar)} atlanacak bolum bulundu."
        )

        return {
            "durum": "basarili",
            "mesaj": analiz_mesaji,
            "kaynak": kaynak,
            "analiz_tipi": "skippable",
            "video_id": video_id,
            "video_basligi": video_basligi,
            "video_url": video_url,
            "video_aciklamasi": video_aciklamasi,
            "video_ozeti": video_ozeti,
            "dil": dil,
            "toplam_parca": len(ham_veri),
            "chapter_sayisi": len(chapters),
            "heatmap_segment_sayisi": len(heatmap_segments),
            "heatmap_kullanildi": heatmap_kullanildi,
            "heatmap_durumu": heatmap_durumu,
            "analiz_id": analiz_id,
            "kullanici_id": kullanici_id,
            "kullanici_analizi_kaydedildi": analiz_id is not None,
            "chapters": chapters,
            "atlanacak_aday_sayisi": len(atlanacak_adaylar),
            "atlanacak_kisim_sayisi": len(atlanacak_kisimlar),
            "atlanacak_kisimlar": atlanacak_kisimlar,
            "onemli_kisim_sayisi": len(atlanacak_kisimlar),
            "onemli_kisimlar": atlanacak_kisimlar
        }

    except Exception as e:
        analysis_locks.discard(video_id)
        db.rollback()
        db.close()
        print("Analiz endpoint hatasi:", repr(e))

        if "remote_llm_" in str(e):
            return {
                "durum": "hata",
                "video_id": video_id,
                "mesaj": "RunPod LLM sunucusuna ulasilamadi veya LLM cevap veremedi.",
                "teknik_hata": str(e)
            }

        if "String or binary data would be truncated" in str(e):
            return {
                "durum": "hata",
                "video_id": video_id,
                "mesaj": "Veritabani kaydi sirasinda bir alanin metin uzunlugu fazla geldi.",
                "teknik_hata": str(e)
            }

        return {
            "durum": "hata",
            "video_id": video_id,
            "mesaj": "Bu videoda altyazı bulunamadı veya işlem sırasında hata oluştu.",
            "teknik_hata": str(e)
        }


@app.post("/api/heatmap-kaydet/{video_id}")
def heatmap_kaydet(video_id: str, request: HeatmapRequest):

    print("🔥 Heatmap geldi:", video_id)
    print("🔥 Segment sayısı:", len(request.heatmap))

    heatmap_segmentleri = [
        item.model_dump() if hasattr(item, "model_dump") else item.dict()
        for item in request.heatmap
    ]

    heatmap_durumu = "available"

    if request.heatmap_unavailable or len(heatmap_segmentleri) == 0:
        heatmap_durumu = "unavailable"

    heatmap_cache[video_id] = {
        "status": heatmap_durumu,
        "segments": heatmap_segmentleri
    }

    return {
        "durum": "basarili",
        "video_id": video_id,
        "heatmap_durumu": heatmap_durumu,
        "heatmap_segment_sayisi": len(heatmap_segmentleri)
    }
