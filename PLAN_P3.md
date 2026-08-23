# P3 — Kalan Teknik Borç Planı

> Durum: Faz 0-3 tamamlandı, P3 = 3 düşük öncelikli kalem
> Sıra: P3-2 (Enter guard) → P3-1 (token/cost) → P3-3 (mypy)

---

## P3-2 — Enter Guard (`send_keys` sarmalama) — ~30 dk

**Mevcut:** Sadece `click` guard'lı; `Enter` tek satırlık input'ta submit tetikleyebilir. Dokümante ama kodda değil.

**Yaklaşım:**
- `GuardedTools`'a `send_keys` wrapper'ı ekle — `click` ile aynı pattern: registry'deki `send_keys`'i overwrite et, `_builtin_send_keys`'i sakla
- Pure helper `is_enter_submission(tag, attributes, keys)`:
  - `keys` içinde `Enter` yoksa → pass
  - Hedef `textarea` / `contenteditable` ise → pass (Enter = newline)
  - `input` type `text|email|password|search|tel|url|number` + `select` + `div[role=textbox]` → **BLOCKED**
- Hedef tespiti: `browser_session.get_element_by_index(params.index)` — click ile aynı lookup
- Block: `ActionResult(error="BLOCKED: Enter in single-line field...")`
- Dosyalar: `agent/safety.py` + `agent/tools.py` + `tests/unit/test_safety.py` + `tests/unit/test_guarded_tools.py`
- Kabul: textarea serbest / input blok — ikisi de unit testli; lint+test yeşil

---

## P3-1 — Token/Cost Takibi — ~1 saat

**Mevcut:** `Agent(calculate_cost=False)` — maliyet hesaplanmıyor, log/analytics/UI'da yok.

**Yaklaşım:**
- `JobFormAgent.run()`'da `Agent(calculate_cost=True)` aç
- `AgentHistory` / `AgentResult` dönüşünden `usage` çıkar — önce `browser-use` kaynağı inspect edilecek
- `AgentLogger.log_step()` satırına opsiyonel `usage` alanı ekle; `summary()`'ye `total_tokens`/`total_cost` ekle
- `analytics.py`: `_parse_run`'da `usage` topla → `aggregate_runs`'ta `total_tokens`/`total_cost`/`avg_cost`
- UI: Run History'a 5. metrik "💰 Cost" + tabloda Cost sütunu (yoksa "—")
- Eski log'larda `usage` yoksa graceful `None`
- Dosyalar: `agent/service.py` + `logging_utils/run_logger.py` + `analytics.py` + `ui/app.py` + ilgili testler
- Risk: browser-use cost API sürümler arası değişken — bulunamazsa dokümante edilip fake data yazılmadan bırakılacak
- Kabul: Yeni log'da usage var / eski log'da çökme yok; ruff+pytest yeşil

---

## P3-3 — mypy — ~1-2 saat

**Mevcut:** `ruff` var, `mypy` yok.

**Yaklaşım:**
- `pyproject.toml`: `mypy==1.13` dev dep + `[tool.mypy]`:
  ```toml
  python_version = "3.11"
  warn_return_any = true
  warn_unused_ignores = true
  ignore_missing_imports = true
  exclude = "tests"
  ```
- `pip install -e ".[dev]"` → `mypy src` → sadece gerçek bug'lar düzeltilir, diğerleri `# type: ignore` ile bastırılır
- CI: `.github/workflows/ci.yml`'a `mypy` job'u ekle
- Dosyalar: `pyproject.toml` + tip düzeltmesi gereken 2-3 kaynak + CI
- Kabul: `mypy src` 0 error; ruff+pytest yeşil

---

## Sıra Gerekçesi

```
P3-2 (bağımsız, hızlı) → P3-1 (logger+analytics'e dokunur, mypy'dan önce bitmeli) → P3-3 (yeni kodu da kapsar)
```

Toplam ~2-3 saat. Her faz küçük commit + test ile.
