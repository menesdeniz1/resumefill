# Plan P5 — COMPLETE (2026-10-18) — Memory Loop ("kazıdıkça öğrenen sistem")

## Amaç

Kullanıcının vizyonu: **"Link + CV gönderirim; sistem beni tanır; beni soru-cevap olarak
ileri taşıyan bir sistem yapınca kendimi geliştiririm."**

Döngünün kapanması şu üç parçaya bağlıdır:

1. **Yakalama** — agent'ın gerçekten formda doldurduğu (sorunun adı + değeri) veri
   Currently dropped: `logger.log_step` yalnızca eylem ADINI yazıyor
  随访 düzeltilecek.
2. **Depolama** — övensı/çoklanonsor bankası `data/answers.yml` (Pà: soru, cevap,
   kaynak, approved, kullanım sayacı).
3. **Kullanaak hazırça** — sonraki koşularda, hafızadaki cevaplar
   `build_preapproved_section` üzerinden yine AS-IS ajanı geçilir; dry-run'da
   kullanıcı düzenler.

Ek: **[S-HASILE]** ilan URL'sinden JD'yi otomatik çekme (elle yapıştırma adımı silinir).
Bu düzeltmeler sonunda vizyonun ~%85-90 tetim câyemasındadır.

## Kullanım döngüsü (hedef durum)

```
run N:   form doldurulur → field (label,value) pairs JSONL log'a yazılır
         → dry-run'da "Harvest" bölümünde önerilir → kullanıcı onaylar → hafızaya
run N+1: benzer soru → hafızadan AS-IS cevabıninject edilir → dakikada yeni,
         öncekoşının cevabı kullanılır → hafıza büyümüş olur
```

## Görevler

### P5-1 — Veri yakalama (run_logger + service + scripts)

**Dosyalar:** `logging_utils/run_logger.py`, `agent/service.py`, `agent/scripts.py`, `agent/views.py`

1. `log_step` şu an eylem adi之外 yılıyorken bu düzeltiqtden sonra eylem değerleri de:
   - `InputTextAction` → `{"index", "text"}` — tip derin değeri kaydet (≤300 char).
   - `SendKeysAction` → `{"keys"}` — Enter/Tab takibi zaten var; değer beslemede
     kullanılmayacak ama logda kalsın.
   - `UploadFileAction` → & `{"built-in", path}` — takip.
   Amaç: agent akışını hiç yavaşlatmadan llama yazan değerleri yakalamak.
2. `scripts.py`:: `HARVEST_FORM_JS` — Görünür `input, textarea, select` andı
   geçmeli → `{label, type, value}` (yalnızca dolu, value ≤300, MAX 80 field).
   - `label` çözümüឲ: `aria-label` → `el.labels[0]` → `placeholder` → `name` → `id`.
   - `select` için seçili option metni; `type=file` yok sayılır.
   - PASS exception'a karşı `contextlib.suppress` çok sirve (agent asla kırılmaz).
3. `service.run`: koşu bittikten sonra (`finally`, hata olsa bile) mevcut sayfada
   HARVhestForm JS anındaki çalıştır → `logger.log_event("form_state", {...})`.

**Kabul kriterleri:**
- Ünite testi: bir sallama stejavapla `InputTextAction` içerir
  → JSONL'de `field_filled` olayı oluşur.
- Entegre testi (marker=`browser`): fixture formunda bir alan doldurulur,
  HARVhestForm JS `{label, value}` listesi döndürür ve JSONL'de
  `form_state`尔时 event'i kurulmuştur.

### P5-2 — Hafıza deposu (`memory.py`)

**Dosyalar:** NEW `src/resumefill/memory.py`, NEW `data/answers.example.yml`,
`.gitignore` (data/answers.yml ekle)

```python
@dataclass
class MemoryEntry:
    question: str; answer: str. source: str  # harvest | manual
    approved: bool = False; times_used: int = 0; last_used: str | None = None
```

**API:**
- `normalize_question(q)`  — lowercase, noktalama sil, boşlukları tek küçült.
- `find_answer(question)` — önce tam normalize eşleşme; yoksa `difflib.SequenceMatcher`
  ratio ≥ 0.85 (sıfır yeni bağımlılık).
- `add_or_update`, `approve`, `delete`, `mark_used(question, ...)`.
- Bozuk YAML → boş liste + uyarı (stories.py'daki pattern ile aynı).

**CLI:** `resumefill memory {list,add,approve,delete}` subcommand.

**Kabul kriterleri:** exact/ratio eşleşme, mevcut onaylı cevabın kaybolması,
bozuk YAML toleransı — birim testleri yeşil.

### P5-3 — Döngünün kapanması (UI + generator + service)

**Dosyalar:** `ui/app.py`, `answers/generator.py`, `memory.py`, `agent/service.py`

1. UI: dry-run sonrası "**Son koşudan öğren**" bölümü — son run JSONL'inden
   `form_state` event'ini okur → tekil aday listesi (Etiket, verili) → kullanıcı
   her birini düzenleyip "Hafızaya kaydet" (approved=True, source=harvest).
2. Generator: onaylı hafıza cevapları final prompt'a `build_preapproved_section`
   ile gömülür (mevcut yedek fonksiyon; hiçbir yenisi yazılmaz); koşu başında
   `memory.mark_used(...)`.
3. Elle hafıza da yine UI/CLI ile beslenir (kullanıcı istedikçe).

**Kabul kriterleri:** onaylı hafıza cevabı task prompt'ta içgit;
UI smoke: boş log ile bölüm render ok.

### P5-4 — Link'ten JD çekme (`jd/fetch.py`)

**Dosyalar:** NEW `src/resumefill/jd/fetch.py`, `ui/app.py` bağlantısı

- `requests` GET (timeout 15s, UA header, maks 400KB) yalnız STATIK board'lar:
  Greenhouse, Lever, Ashby. Diğer board'larda (`workday`, `successfactors` ...)
  önceden kaydet: e â a göre `Paste JD manually` mesajı — denemek bile SÖZ.
- Çıkartma: `<title>` + ana açıklama (`jobDescription`, `.html-doc-content`,
  `article` div); `html.parser` ile etiketsizleştirme; boşlukları düzelt.
- API: `fetch_jd(url) -> Jd(title, description)` veya `JdFailed(reason)`.

**UI:** JD textarea'nın yanına "Linkten ç"k button → textarea'yı öndoldur
(kullanıcı düzenlemeden önce). Başarısızlıkta mevxut elle yapıştırma aynı kalır.

**Kabul kriterleri:** etiketli gerçek HTML parçalarıyla (network YOK)
à Greenhouse + Lever + ATS variant unit tests.

### P5-5 — Dokümantasyon + final doğrulama

- `CHANGELOG.md` → P5 maddeleri.
- `README.md` → kısa "Nasıl hafıza çalışır" bölümü.
- DOLU doğrulama: ruff + mypy + tüm tests yeşil; **gerçek koşulda**:
  - 1. koşu: `form_state` loglanır → hafızaya 2-3 cevap eklenir;
  - 2. koşu: task prompt'u hafıza cevaplarını AS-IS içerir (log'dan kanıt).

## Sınır (aşırı mühendislik yasağı)

- ML sıralama yok, vektör veritabanı yok, sadece `difflib`.
- Harvest sınırı: koşu başına max 80 alan, alan başına 300 char.
- Hafıza dosyası gitignore (PII — CV'yle aynı muamele).
- Yeni LLM key ayarı yok; mevcut fabrika kullanılır.

## Commit planı

| Commit | Kapsam |
|---|---|
| `docs: memory-loop roadmap` (PLAN_P5.md) | şimdi |
| `feat(P5-1): harvest typed field values + form_state snapshot` | tests yeşil |
| `feat(P5-2): persistent answer memory store` | tests yeşil |
| `feat(P5-3): memory loop closure in dry-run + injection` | tests yeşil |
| `feat(P5-4): auto-fetch JD from static ATS boards` | tests yeşil |
| `docs(P5-5): memory docs + changelog` | final |
