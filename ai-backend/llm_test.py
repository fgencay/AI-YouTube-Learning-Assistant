from transformers import pipeline
import re
import json

model = pipeline(
    "text-generation",
    model="Qwen/Qwen2.5-0.5B-Instruct",
    device=-1
)

prompt = """
Aşağıdaki transcript satırlarından sadece eğitim açısından önemli olan satır numaralarını seç.

Kurallar:
- Sadece sayı listesi ver.
- Açıklama yazma.
- JSON dışına çıkma.
- Abone ol, beğen, reklam, sponsor satırlarını seçme.

Cevap formatı:
[1, 3, 4]

Transcript:
1. [0.0 - 5.0] Bu derste Python programlamaya giriş yapacağız.
2. [5.0 - 10.0] Videoyu beğenmeyi ve abone olmayı unutmayın.
3. [10.0 - 20.0] Değişkenler verileri bellekte saklamak için kullanılır.
4. [20.0 - 30.0] Fonksiyonlar tekrar kullanılabilir kod bloklarıdır.

Cevap:
"""

cevap = model(
    prompt,
    max_new_tokens=80,
    do_sample=False,
    return_full_text=False
)

uretilen_metin = cevap[0]["generated_text"]

print("HAM MODEL CEVABI:")
print(uretilen_metin)

eslesme = re.search(r"\[[0-9,\s]+\]", uretilen_metin)

if eslesme:
    secilen_indexler = json.loads(eslesme.group())
    print("SEÇİLEN INDEXLER:")
    print(secilen_indexler)
else:
    print("Liste bulunamadı.")