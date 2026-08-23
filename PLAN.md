# resumefill — Ürünleştirme Planı

> Durum: Faz 0-1 tamamlandı · Sıradaki: Faz 2A
> Karar günlüğü: dry-run = **Answer Pack** · dağıtım = **Streamlit + ince CLI** · Docker/PII ekranı kapsam dışı

## Tamamlananlar (referans)

| Faz | Kalem | Durum |
|-----|-------|-------|
| 0 | pinned deps, encoding/sanitizer, sleep(10), max_steps, gitignore/temp cleanup, path/port fix, submit guard | ✅ |
| 1 | katmanlı mimari, platform tespiti, config (dataclass+env), fixture'lar | ✅ |
| 3 | pytest (unit+browser), CI (ruff+pytest), README | ✅ |

Kalan borçlar bu planda: structured output, profil kalıcılığı, analitik, dağıtım.

---

## Faz 2A — Profil Deposu (~1 gün)

**Hedef:** CV her koşuda yeniden analiz edilmesin; profiller saklansın, düzenlensin, çoklu varyant desteklensin.

- `ProfileStore`: `data/profiles/<slug>.json`
  - İçerik: `{schema_version, name, email, phone, title, analysis, style_profile, source_cv_sha256, created_at, updated_at}`
  - Slug isimden türetilir; çakışmada `-2` soneki
- Analiz başarılı olunca otomatik kaydet; UI'da "kaynaklı/yeniden kullan" akışı:
  - Upload varsa → analiz → kaydet
  - Profil seçilirse → LLM çağrısı yok, doğrudan koşu
- UI: profil dropdown + anahtar alan düzenleme (name/email/phone/title) + sil
- Şema sürümü ile ileriye dönük uyumluluk (`schema_version=1`)
- **Kabulum:** ProfileStore %100 unit-testli (tmp_path üzerinde); UI ince kalır

## Faz 2B — Dry-run: Answer Pack + Cevap Editörü (1-2 gün)

**Hedef:** Ajan hiç tarayıcı açmadan kişiselleştirilmiş cevaplar üretip göstersin; kullanıcı düzenleyip onaylasın.

- `AnswerPack` üretici: persona + profil (+JD, Faz 2C) → yaygın soru tipleri için cevap seti
  - Soru tipleri: about-you, why-this-role*, strengths, weakness, notice-period, salary-expectation, team-conflict, why-leaving (*JD gerekli)
  - Tek LLM çağrısında structured JSON olarak tüm paket (Faz 2E ile sağlamlaşır)
- UI: editör tablosu (soru / cevap metin alanı) + "Onayla ve Koştur"
- Onaylanan cevaplar prompt'a `PRE-APPROVED ANSWERS — use VERBATIM when matching question appears` bölümüyle gömülür
- Formda beklenmeyen sorular çıkarsa ajan yine persona ile canlı yanıtlar
- **Kabulum:** AnswerPack üretimi mock-LLM ile testli; prompt gömme fonksiyonu pure ve testli

## Faz 2C — JD Uyarlama (~yarım gün, 2B ile birlikte)

**Hedef:** "Why this role?" cevapları gerçek ilan metnine dayansın.

- UI paste alanı: job description metni
- Prompt'a `JOB DESCRIPTION` bölümü + persona talimatı: "vurgularını bu ilanın gereksinimlerine hizala"
- Answer Pack üretimine JD girdisi (why-this-role/strengths cevapları role-specific olur)
- **Kabulum:** prompt builder pure testler; JD yoksa ilgili bölümler düşer, akış bozulmaz

## Faz 2D — Analitik Paneli (~1 gün)

**Hedef:** Hangi platformda kaç koşu, başarı oranı, nerede takıldığını gör.

- `analytics.py`: `logs/*.jsonl` → aggregate dict (koşu sayısı, başarı, adım/hata ort., platform/domain kırılımı, süre)
- Browser-use `calculate_cost`/token bilgisi yakalanabilirse koşu özetine ekle
- UI: "📈 History" görünümü (metric'ler + son koşular tablosu)
- **Kabulum:** agregatör sentetik JSONL fixture'larıyla unit-testli

## Faz 2E — Structured Output (~yarım gün)

**Hedef:** CV analizi JSON'unu regex fallback'e değil native şemaya dayandır.

- `analyze_cv` → langchain/browser-use `response_schema` ile zorlanmış JSON
- Mevcut `parse_profile_json` fallback + regression testleri aynen kalır
- **Kabulum:** mock-LLM ile hem schema hem fallback yolu testli

## Faz 3 — Dağıtım & Hijyen (~1 gün)

- İnce CLI (argparse, yeni bağımlılık yok):
  ```
  resumefill run <url> [--profile SLUG] [--cv PATH] [--jd FILE] [--dry-run] [--headless]
  resumefill profiles [list|show SLUG]
  ```
- Dry-run CLI'da = Answer Pack üret + terminale yaz (onay akışı UI'da)
- `CHANGELOG.md` başlat (Keep-a-Changelog, SemVer)
- Docker/pipx-publish: bilinçli olarak kapsam dışı (şahsi kullanım, YAGNI)

---

## Sıralama Gerekçesi

```
2A (profil) ──▶ 2B (dry-run) ──▶ 2C (JD) ──▶ 2D (analitik) ──▶ 2E (structured output) ─▶ 3 (CLI)
     ▲               ▲______________│
     │___ 2B ve 2C profilleri tüketir; analitik en son, oluşan logları okur
```

Toplam ~4-5 gün. Her faz: küçük commitler + testler aynı PR/commit içinde, çalışmadan commit yok.
