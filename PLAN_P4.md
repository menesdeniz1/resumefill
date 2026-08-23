# P4 — Rekabet Analizinden Çıkan Özellikler (career-ops & AIHawk ilhamı)

> **Kime:** Uygulayacak geliştiriciye (junior/mid) senior'dan talimatlar
> **Kaynak:** santifer/career-ops (filtre felsefesi, A-H rubrik, Block G) ve feder-cr/AIHawk (hacim yaklaşımının kaçındığımız yanları)
> **Sıra:** P4-2 → P4-1 → P4-4 → P4-3 · Toplam ~10 saat
> **Altın kural:** Hiçbir yeni özellik akışı bloklayamaz, submit kararını değiştiremez, ağ çağrısı ekleyemez.

---

## Global Kurallar (her görevde geçerli)

1. **Human-in-the-loop bozulmaz.** Skor/uyarı sadece *karar destek*; hiçbir şeyi engellemez, hiçbir şeyi otomatikleştirmez.
2. **Sıfır ek bağımlılık hedefle.** Sadece P4-4 `PyYAML` ekler (zaten transitive var, explicit declare edeceğiz).
3. **Her pure fonksiyon testlidir; LLM çağıran kod mock'lanır.** Network'e değen test yasak.
4. **Metin her yerde `sanitize_text`'ten geçer** (JD yapıştırması da kullanıcı girdisidir).
5. **Prompt'lar modül sabitidir** (`*_PROMPT`), format parametreleri dışında gövde değişmez.
6. **Commit disiplini:** Her P4-x kendi commit'i; lint+mypy+pytest yeşil olmadan commit yok.
7. **YAGNI:** Aşağıda "Kapsam Dışı" yazan şeyi merak etme bile. Portal scanner, e-mail gönderme, embeddings, çoklu kullanıcı — hepsi yasak.

---

## P4-2 — İlan Meşruiyet Taraması ("mini Block G") — ~2 saat

**Amaç:** Kullanıcı JD yapıştırdığında, token harcamadan **saf kural tabanlı** kırmızı bayrak taraması. career-ops'un Block G'sinin minimal kardeşi.

### Tasarım Kararları (ben verdim, tartışma)

- Yeni modül: `src/resumefill/screening.py`. LLM YOK — %100 deterministik fonksiyonlar.
- Girdi: `jd_text: str`, `url: str | None`, `history_urls: set[str]` (analytics'ten gelir).
- Çıktı: `list[Flag]` where `Flag = {"level": Literal["info","warn","danger"], "code": str, "message": str}`.
- Repost tespiti: URL normalize et (scheme at, query string at, trailing slash at) → history_urls içinde aynı normalize edilmiş URL varsa `warn` "bu ilan daha önce görülmüş". Tarih karşılaştırma YOK (loglarda güvenilir tarih eşlemesi yok — basit tut).
- URL kısaltıcı domainleri (`bit.ly`, `tinyurl.com`, `t.co`...) → `info`.

### Kontrol Listesi (tablo sürümlü, hepsi `dataclass` değil düzyazı sabitler)

| code | level | Tetikleyici (case-insensitive, JD text üzerinde) |
|------|-------|--------------------------------------------------|
| `fee_request` | danger | `"training fee"`, `"registration fee"`, `"pay" AND ("kit" OR "background check fee")`, `"send money"` |
| `crypto_payment` | danger | `"crypto"`, `"usdt"`, `"bitcoin"` + `"salary"/"payment"` aynı cümlede |
| `personal_apply_email` | warn | JD içinde `@gmail.com/@hotmail.com/@outlook.com/@yahoo.com` taşıyan e-posta |
| `commission_only` | warn | `"commission only"`, `"unlimited income"`, `"be your own boss"` |
| `whatsapp_only` | warn | `"whatsapp"` ile iletişim talebi |
| `too_short` | info | sanitize sonrası < 200 karakter |
| `no_company_name` | info | JD'de büyük harfli kurumsal sinyal yok (basit sezgisel: `"we are"`, `"our team"`, `"about us"` geçmiyor) VE uzunluk > 400 karakter değilse |
| `shortened_url` | info | yukarıdaki kısaltıcılar |
| `repost` | warn | normalize URL history'de var |

**Kırmızı çizgi:** Yanlış pozitif toleransımız düşük olsun — şüphede `warn` kullan, `danger` sadece açık dolandırıcılık sinyalinde. Bu bir *danışman*, hakim değil.

### Görevler

1. `screening.py`: `normalize_url(url) -> str`, `screen_jd(jd_text, url=None, history_urls=None) -> list[Flag]`
2. Sabitler: `_DANGER_PATTERNS`, `_WARN_PHRASES`, `_SHORTENER_DOMAINS` — frozenset/tuple, modül seviyesinde
3. Test dosyası `tests/unit/test_screening.py`: her flag için pozitif+negatif case (tablo sürümlü `pytest.mark.parametrize`); normalize_url edge case'leri (`https://x.com/a?utm=1` ≡ `x.com/a`)
4. UI entegrasyonu (`ui/app.py` dry-run bölümü): "Generate draft answers" basılınca screen sonucu `st.markdown` bloğu olarak göster — `danger` kırmızı, `warn` sarı, `info` gri. **Akışı durdurma.**
5. Loglama: dry-run handler'a `logger.log_event("jd_screening", {"flags": [...]})` — logger zaten elimizde.

### Kabul Kriterleri

- [ ] `screen_jd("", None)` → boş liste, exception yok
- [ ] Dolandırıcılık cümlesi içeren sahte JD testte `fee_request: danger` üretiyor
- [ ] Repost: aynı URL ikinci kez → tam 1 adet `repost` uyarısı
- [ ] `ruff` + `mypy` temiz; tüm mevcut testler hâlâ yeşil

### Kapsam Dışı

Site scraping, ilan yaşı sorgulama, harici API, company-name doğrulama servisi.

---

## P4-1 — Uyum Skoru Rubriği (1-5 + gerekçe) — ~3 saat

**Amaç:** JD girildiğinde CV-vs-ilan uyumunu 5 boyutta puanla, holistik genel skor ve "başvurmalı mıyım" özeti üret. career-ops'un A-H raporunun tek-sayfalık özeti. **Karar kullanıcıda kalır.**

### Tasarım Kararları

- Yeni modül: `src/resumefill/scoring.py`
- **Tek LLM çağrısı**, native structured output (P3'te kurduğumuz `with_structured_output` altyapısını kullan — `cv/analyzer.py::analyze_cv`'deki pattern'i birebir takip et: `_structured_chain` + degrade-to-text path)
- Skor **LLM'in holistik yargısı** — aritmetik ağırlıklı formül YOK (career-ops bilinçli olarak böyle yapıyor; formül oyunlaştırılır)
- JD yoksa özellik çalışmaz (sessizce atlanır — UI'da buton zaten JD bölümünün altında değil, dry-run akışının içinde)
- Skor hiçbir şeyi engellemez; dry-run çıktısının en üstünde gösterilir

### Şema (pydantic, `CvProfileSchema` pattern'iyle)

```python
class DimensionScore(BaseModel):
    name: str            # sabit 5 boyuttan biri
    score: float         # 1.0–5.0
    rationale: str       # 1-2 cümle, CV'den kanıt referanslı

class FitReport(BaseModel):
    global_score: float              # 1.0–5.0
    verdict: Literal["strong", "reasonable", "stretch", "skip"]
    dimensions: list[DimensionScore] # tam 5 öğe
    red_flags: list[str]
    summary: str                     # 2-3 cümle net tavsiye
```

Boyut sabitleri (modül sabiti `_DIMENSIONS`): `skills_match`, `experience_level`, `domain_overlap`, `growth_comp`, `logistics`. Prompt'ta her boyutun tanımı + "kanıt göster" talimatı olacak.

### Görevler

1. `scoring.py`: `FitReport`/`DimensionScore` şemaları + `FIT_PROMPT` + `evaluate_fit(cv_text, jd_text, llm, fallback_llm=None, sleep=time.sleep) -> FitReport`
   - Structured path başarısızsa → text fallback + `parse_profile_json` benzeri tolerant parse (adını `parse_fit_report` koy, `ValueError` yükseltir)
   - Parse edilemeyen çıktıda **minimal degrade**: boş dimensions'lı nötr rapor döndür, crash etme (`cv/analyzer.py::_MINIMAL_PROFILE_TEMPLATE` deseni)
   - `sanitize_text` hem cv_text hem jd_text'e uygulanır; jd_text 8000 karakterle kesilir (token bütçesi — `answers/generator.py`'deki `[:6000]` deseni)
2. Doğrulama: `dimensions` eksik/gelmediyse 5 boyutu default `score=0.0, rationale="not evaluated"` ile tamamla (`_fill_dimensions` helper)
3. Testler `tests/unit/test_scoring.py`:
   - Mock structured chain → dict dönüş doğru mapleniyor
   - Text fallback: fenced JSON parse ediliyor
   - Eksik boyut → default doldurma
   - `verdict` geçersiz gelirse `"reasonable"`a clamp'leniyor
4. UI entegrasyonu: dry-run "Generate draft answers" akışında, answer pack'ten **önce** çağrılır; sonuç `st.metric(global_score)` + boyut tablosu (`st.dataframe`) + `summary` caption olarak gösterilir. `verdict == "skip"` ise kırmızı bilgi kutusu — ama akır devam eder
5. CLI: `resumefill run <url> --jd FILE --dry-run` çıktısına skor bloğu ekle (aynı `evaluate_fit`, print ile)

### Kabul Kriterleri

- [ ] JD'siz çağrıda fonksiyon hiç invoke olmuyor (UI akışında guard var)
- [ ] Mock LLM ile test network'süz geçiyor
- [ ] Bozuk JSON → nötr rapor, exception yok
- [ ] `ruff` + `mypy` + tüm testler yeşil

### Kapsam Dışı

Ağırlık konfigürasyonu, geçmiş skorların trend grafiği, portal-wide sıralama.

---

## P4-4 — STAR Hikâye Bankası — ~2 saat

**Amaç:** Persona statik kalıyor; kullanıcı bir kere mülakat hikâyelerini yazsın, answer pack ilgili olanları kanıt olarak kullansın. career-ops'un "Story Bank"inin hafif versiyonu.

### Tasarım Kararları

- Depo: `data/stories.yml` — **tek YAML dosyası** (JSONL insan-editine uygun değil). `PyYAML` zaten environment'ta (`streamlit` transitive); `pyproject.toml` dependencies'e `PyYAML==6.0.3` explicit ekle
- Şema:
```yaml
stories:
  - title: "AOI sistemi ile CAPEX düşürme"
    tags: [computer-vision, cost-reduction, industrial]
    situation: "..."
    task: "..."
    action: "..."
    result: "%88 CAPEX tasarrufu..."
    reflection: "Öğrendim ki..."
```
- Seçim algoritması: **embedding YOK.** Basit token örtüşmesi: JD'nin alt-dizgilerindeki kelimeler ∩ story'nin `tags+title+result` kelimeleri (stopword'lü küçük bir `_STOPWORDS` sabiti). En iyi 2 story seçilir; skoru sıfır olan hiçbiri seçilmez.
- Dosya yoksa / boşsa: özellik sessizce devre dışı — answer pack davranışı bugünkü gibi. **Zorunlu bağımlılık değildir.**

### Görevler

1. Yeni modül `src/resumefill/stories.py`:
   - `Story` dataclass (title, tags, situation, task, action, result, reflection)
   - `load_stories(path) -> list[Story]` — bozuk kayıt atlanır, dosya yoksa `[]`
   - `select_relevant(stories, jd_text, k=2) -> list[Story]`
   - `build_stories_section(stories) -> str` (prompt'a eklenecek markdown bloğu; boşsa `""`)
2. `data/stories.example.yml` oluştur (2 örnek story, gerçek CV'den — `data/cv.txt`'deki AOI/LiDAR işlerinden)
3. `answers/generator.py`: `generate_answer_pack(..., stories: list[Story] | None = None)` — prompt'a `{stories_section}` ekle + kural satırı: "When a story is relevant, ground your answer in its specifics"
4. UI: dry-run bölümünde stories dosyası varsa `st.caption("N stories loaded")`; çağrıya `stories=` geçir
5. CLI: `resumefill run --jd FILE` zincirinde aynı şekilde geçir; `data/stories.example.yml` → README'de bahset
6. Testler `tests/unit/test_stories.py`: yükleme/bozuk-satır atlama/seçim skoru/prompt embedding/dosya-yok senaryosu

### Kabul Kriterleri

- [ ] `stories.yml` hiç yokken tüm akış bugünkü gibi çalışıyor (regression!)
- [ ] İlgisiz JD'de hiçbir story seçilmiyor
- [ ] YAML sözdizimi hatasında graceful `[]` + stderr uyarısı, crash yok

### Kapsam Dışı

Embeddings, story editörü UI'ı, otomatik story çıkarma.

---

## P4-3 — Başvuru Sonuç Takibi (funnel) — ~3 saat

**Amaç:** Analytics şu an koşu sağlığına bakıyor; başvuru *sonuçlarını* görmüyor. career-ops'un funnel/pattern fikrinin minimal hali: hangi platformda ilerliyorsun?

### Tasarım Kararları

- Depo: `data/outcomes.jsonl` — append-only, her satır:
```json
{"timestamp": "...", "url": "...", "platform": "lever", "profile_slug": "...", "status": "interview", "notes": ""}
```
- Status enum (`platforms.py`'deki `StrEnum` pattern'i): `applied, interview, offer, rejected, ghosted`
- Bir URL'in son durumu = en güncel kaydı (append-only + latest-wins; güncelleme = yeni satır — geçmiş korunur)
- **PII notu:** `data/outcomes.jsonl` `.gitignore`'a eklenecek (profil slug + URL içeriyor)

### Görevler

1. Yeni modül `src/resumefill/outcomes.py`:
   - `OutcomeStatus(StrEnum)`, `Outcome` dataclass
   - `OutcomeStore(directory)`: `record(url, status, profile_slug=None, notes="")`, `latest_by_url() -> dict[str, Outcome]`, `aggregate() -> dict` (`{status: count}` + platform kırılımı + platform→interview-oranı)
   - Yazma atomic-append (satır sonu `\n` garanti); okuma corrupt-satır-atlar (`analytics.py` pattern'i)
2. CLI: `resumefill outcome <url> --status STATUS [--notes TEXT] [--profile SLUG]`
   - Geçersiz status → argparse `choices` ile elenir
3. Analytics köprüsü: `aggregate_runs`'a dokunma (koşu metriği ayrı kalır); UI Run History bölümüne **ikinci dataframe**: "Başvuru Hunisi" — status sayaçları + platform bazında `applied→interview` oran
4. UI: Run History altına mini form (`st.text_input` URL + `st.selectbox` status + `st.button` Record) — kaydedince `st.rerun()`
5. `.gitignore` + README + CHANGELOG güncelle
6. Testler `tests/unit/test_outcomes.py`: record/latest-wins/aggregate matematiği/corrupt satır/geçersiz status

### Kabul Kriterleri

- [ ] Aynı URL'e `applied` sonra `interview` → aggregate'te applied=0 görünmez; latest-wins doğru sayar (funnel sayacı **anlık durum**, kümülatif değil)
- [ ] Bozuk JSONL satırı diğerlerini bozmuyor
- [ ] `git check-ignore data/outcomes.jsonl` doğrulandı

### Kapsam Dışı

Otomatik reply-reading (career-ops'un `reply-watch`'ı), takvim/remind sistemi, trend grafikleri.

---

## Uygulama Sırası ve Nedeni

```
P4-2 screening  (2s) ── saf fonksiyonlar, sıfır risk, hızlı kazanım, test alışkanlığı
   ↓
P4-1 scoring    (3s) ── structured-output altyapısını yeniden kullanır; dry-run akışını zenginleştirir
   ↓
P4-4 stories    (2s) ── answer pack'i besler; P4-1 ile aynı UI noktasına dokunur
   ↓
P4-3 outcomes   (3s) ── en sonda: hem CLI hem UI hem analytics'e dokunur; üsttekilerin kurulduğu zemini kullanır
```

## Genel Tanım (Definition of Done — tüm görevlerin ortak şartı)

- `ruff check src tests` → 0 sorun
- `mypy src` → 0 hata
- `pytest tests -q` → tümü yeşil (network/browser'sız unit'ler dahil)
- `streamlit run` boot smoke HTTP 200
- CHANGELOG `[Unreleased]` altına giriş; etkilenen README bölümleri güncel
- Küçük commit: her P4-x en az 1 feat commit + gerekirse içi fix commit'ler

## Bilinen Tuzaklar (junior için özel notlar)

1. `QUESTION_SLOTS`'ta olduğu gibi **sözlük değer tipi** mypy'yı patlatır — `TypedDict` kullan (`SlotInfo` dersini hatırla).
2. Streamlit `session_state` anahtarlarında prefix disiplinini koru (`pf_`, `ap_`, yeni: `scr_`, `fit_`). Çakışırsa widget state bozulur.
3. `st.rerun()` sadece mutasyon sonrası; render ortasında çağırma.
4. Windows: her `open()` çağrisında `encoding="utf-8"` unutma — mojibake dersini unutmayalım.
5. LLM mock'ları `tests/unit/fakes.py`'ten; kendi fake'ini local tanımlama.
6. `dataclasses.replace` frozen olmayan dataclass'ta da çalışır ama `CvProfile` gibi paylaşılan nesnelerde mutasyondan kaçın.
