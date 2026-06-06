# Bio Extract Design

**Date:** 2026-06-06
**Scope:** Extract only — land raw bio/profile landing files for deputies (Câmara) and senators (Senado). Transform/build/site are out of scope.

---

## Overview

Two new extract modules, one per house, following the exact conventions of `extract/camara/historico.py` and `extract/senado/detalhe.py`. Each crawls a per-entity detail endpoint and writes one provenance-wrapped JSON file per parliamentarian. No existing modules are modified except `common/http_client.py` (one new method) and `common/paths.py` (two new helpers).

| | Câmara | Senado |
|---|---|---|
| Module | `extract/camara/bio.py` | `extract/senado/bio.py` |
| Endpoint | `GET /deputados/{id}` | `GET /senador/{codigo}` |
| IDs sourced from | roster landing files (same as `historico.py`) | roster landing files (`extract.senado.lista.senator_codes_from_roster`) |
| Output dir | `data/raw/camara/bio/` | `data/raw/senado/bio/` |
| File per entity | `{id}.json` | `{codigo}.json` |

---

## Infrastructure changes

### `CamaraClient.get()` — `common/http_client.py`

`GET /deputados/{id}` returns a single object in `dados`, not a paginated list. `get_all()` would fail on a dict. Add a `get(path, params=None)` method to `CamaraClient` that mirrors the already-present `SenadoClient.get()`: single HTTP call, same retry/backoff behaviour, returns the parsed JSON dict.

No other changes to the client.

### Path helpers — `common/paths.py`

```python
camara_bio_path(deputy_id, base=None)  ->  data/raw/camara/bio/{id}.json
senado_bio_path(codigo, base=None)     ->  data/raw/senado/bio/{codigo}.json
```

Same signature pattern as all other path helpers in the module.

---

## `extract/camara/bio.py`

Fetches `GET /deputados/{id}` for every deputy in the roster landing files and writes one landing file per deputy.

**Key functions:**

- `deputy_ids_from_roster(raw_base, legislatures)` — collect unique deputy IDs from the roster landing files; import directly from `extract.camara.historico` (the function is already defined there)
- `build_payload(deputy_id, data, fetched_at)` — wraps raw API response with `_meta` (source, endpoint, deputy_id, fetched_at) and `dados`; `dados` is the single dict returned by the Câmara API
- `run(client, deputy_ids, raw_base, out_dir, delay, skip_existing)` — crawl loop; `skip_existing=True` by default

**Crawl behaviour:**
- `skip_existing=True`: skips deputies whose file already exists (re-run resumes, not restarts)
- One failure (exception on a single deputy) is logged and skipped; never aborts the whole crawl
- Failed IDs printed at end for manual retry
- `delay` defaults to `client.page_delay`

---

## `extract/senado/bio.py`

Fetches `GET /senador/{codigo}` for every senator in the roster landing files.

**Key functions:**

- `senator_codes_from_roster` — imported from `extract.senado.lista` (already exists)
- `build_payload(codigo, data, fetched_at)` — wraps with `_meta` (source, endpoint, codigo, fetched_at) and `dados`; `dados` is the full Senado response envelope verbatim
- `run(client, codigos, raw_base, out_dir, delay, skip_existing)` — same crawl pattern as Câmara

**Crawl behaviour:** identical to Câmara module above.

---

## Testing

TDD — tests use injected fake clients (no real HTTP).

### `CamaraClient.get()`
- Happy path: returns parsed JSON dict
- 5xx: retries up to `max_retries`, then raises

### `extract/camara/bio.py`
- `build_payload()`: correct `_meta` fields (source, endpoint, deputy_id, fetched_at, record structure)
- `deputy_ids_from_roster()`: reads fixture roster files, returns deduplicated sorted IDs
- `run()` with fake client:
  - writes one file per ID at the correct path
  - `skip_existing=True` skips deputies whose file already exists
  - a client exception on one deputy is logged and skipped; other deputies still written
  - returns only the newly written paths

### `extract/senado/bio.py`
- Same test structure as Câmara module
- `senator_codes_from_roster` import verified (already tested in `lista` tests)

### `common/paths.py`
- `camara_bio_path` and `senado_bio_path`: covered by the parametric path tests alongside existing helpers

---

## Run order

No new ordering constraint. These modules depend only on the roster landing files (already produced by the existing extract steps). They can be re-run independently at any time; `skip_existing` makes them cheap to re-run after partial failures.

```
extract/camara/deputados.py   (roster — prerequisite)
extract/camara/bio.py         (new)

extract/senado/lista.py       (roster — prerequisite)
extract/senado/bio.py         (new)
```

---

## Out of scope

- Transform: no new DB columns; existing `deputy` / `senator` tables unchanged
- Build: no changes to `{id}.json` output
- Site: no frontend changes
- The open deferral "Deputy bio/detail fields" in `decisions.md` is undeferred only up to the extract step here; transform/build wiring is a follow-on spec
