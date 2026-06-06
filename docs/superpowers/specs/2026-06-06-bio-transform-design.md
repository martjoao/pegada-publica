# Bio Transform Design

**Date:** 2026-06-06
**Status:** approved
**Scope:** Bio transform only — enrich `deputy` and `senator` tables with nullable bio columns from the bio landing files. Build/site wiring is out of scope.

---

## Overview

Integrate bio field population into the existing `transform/camara/deputados.py` and `transform/senado/senadores.py` scripts. Each module gains a `load_bio()` function (mirroring the existing `load_roster()` pattern) that reads the per-entity bio landing files and returns a dict of canonical bio fields. The `transform()` function merges this dict with the roster data before the INSERT.

No new transform scripts. No second SQL pass. Bio columns are written in the same `INSERT` as the existing deputy/senator row.

**Prerequisite:** Bio landing files must exist under `data/raw/camara/bio/` and `data/raw/senado/bio/` (produced by `extract/camara/bio.py` and `extract/senado/bio.py` — decision 024). Missing files are tolerated: deputies/senators with no bio file get NULL bio columns.

---

## Schema Changes (`transform/db.py`)

New nullable columns added directly to the `CREATE TABLE` statements. The transform is a full rebuild (DROP + CREATE), so no `ALTER TABLE` needed.

### `deputy` table

```sql
cpf           TEXT,   -- internal only; LGPD-protected; used for TSE linking in spec 2
civil_name    TEXT,   -- nomeCivil
date_of_birth TEXT,   -- dataNascimento (ISO-8601 date)
date_of_death TEXT,   -- dataFalecimento (ISO-8601 date, nullable)
sex           TEXT,   -- 'M' or 'F'
birth_state   TEXT,   -- ufNascimento (UF sigla)
birth_city    TEXT,   -- municipioNascimento
education     TEXT,   -- escolaridade
social_media  TEXT,   -- redeSocial[] serialized as JSON string
website       TEXT    -- urlWebsite
```

### `senator` table

```sql
civil_name    TEXT,   -- NomeCompletoParlamentar
date_of_birth TEXT,   -- DadosBasicosParlamentar.DataNascimento (ISO-8601 date)
birth_state   TEXT,   -- UfNaturalidade (UF sigla)
birth_city    TEXT,   -- Naturalidade (city name)
sex           TEXT,   -- 'M' or 'F' (normalized from Masculino/Feminino)
email         TEXT    -- EmailParlamentar
```

**Note:** `senator.cpf` is deferred to the TSE transform spec (spec 2). The Senado bio API does not expose senator CPFs; that column's sole writer is the TSE transform. `senator` also has no `social_media` or `website` columns — the Senado bio endpoint does not provide those fields.

---

## Data Flow

### `transform/camara/deputados.py` — `load_bio(deputy_ids, raw_base)`

- Iterates over `deputy_ids`, reads `paths.camara_bio_path(id, base=raw_base)`
- Extracts from `dados`:

| Raw PT field | Canonical EN column | Notes |
|---|---|---|
| `cpf` | `cpf` | Store as-is; never surface to users |
| `nomeCivil` | `civil_name` | |
| `dataNascimento` | `date_of_birth` | ISO-8601 date string, pass through |
| `dataFalecimento` | `date_of_death` | NULL if absent or falsy |
| `sexo` | `sex` | Already `'M'`/`'F'` from Câmara API |
| `ufNascimento` | `birth_state` | |
| `municipioNascimento` | `birth_city` | |
| `escolaridade` | `education` | |
| `redeSocial` | `social_media` | Serialize list to JSON string; `'[]'` if empty |
| `urlWebsite` | `website` | |

- Missing file → ID absent from returned dict; all bio columns insert as NULL
- Returns `Dict[int, Dict[str, Any]]`

### `transform/senado/senadores.py` — `load_bio(codigos, raw_base)`

- Reads `paths.senado_bio_path(codigo, base=raw_base)`
- Navigates nested structure: `dados["DetalheParlamentar"]["Parlamentar"]`
  - `IdentificacaoParlamentar`: `NomeCompletoParlamentar`→`civil_name`, `SexoParlamentar`→`sex`, `EmailParlamentar`→`email`
  - `DadosBasicosParlamentar`: `DataNascimento`→`date_of_birth`, `Naturalidade`→`birth_city`, `UfNaturalidade`→`birth_state`
- Sex normalization: `"Masculino"` → `"M"`, `"Feminino"` → `"F"`
- Missing file → absent from returned dict
- Returns `Dict[int, Dict[str, Any]]`

### Integration in `transform()`

Both modules:
1. Call `load_bio()` after `load_roster()` (before the INSERT loop)
2. Merge bio dict into the per-entity data before `INSERT INTO deputy/senator (...) VALUES (...)`
3. Bio fields default to `None` if the entity has no bio entry

One transaction, one pass — no schema migration needed.

---

## Error Handling

- Missing bio file: silently skip — all bio columns NULL for that entity
- Malformed JSON in bio file: propagate exception (operator re-runs extract for that entity)
- Unexpected `dados` structure (e.g. missing nested key in senator response): use `.get()` chains returning `None`; never crash the whole transform on one bad file

---

## Testing

TDD convention: raw PT inputs, canonical-EN assertions, injectable `raw_base`.

### `tests/test_transform_camara_bio.py`

- `load_bio()` with a fixture bio file: all fields map to correct canonical keys
- `redeSocial` non-empty list serialized to valid JSON string
- `redeSocial` empty list → `'[]'`
- Missing bio file for an ID → that ID absent from returned dict (no crash)
- `transform()` end-to-end with minimal roster + bio fixtures: bio columns present on inserted `deputy` row
- Deputy with no bio file → row inserted with `NULL` bio columns

### `tests/test_transform_senado_bio.py`

- `load_bio()` with fixture senator bio: correct field extraction from nested structure
- Sex normalization: `"Masculino"` → `"M"`, `"Feminino"` → `"F"`
- Missing file → absent from returned dict

### `tests/test_db_schema.py` (extend existing)

- `deputy` table has all new bio columns (nullable)
- `senator` table has all new bio columns (nullable)

---

## Run Order

No new ordering constraint. Bio files must exist before transform runs, but that was already implied by the extract → transform pipeline order.

```
extract/camara/deputados.py    (roster — existing prerequisite)
extract/camara/bio.py          (bio — prerequisite)
transform/camara/deputados.py  (now also reads bio files)

extract/senado/lista.py        (roster — existing prerequisite)
extract/senado/bio.py          (bio — prerequisite)
transform/senado/senadores.py  (now also reads bio files)
```

---

## Out of Scope

- Build wiring: `{id}.json` output not yet updated — deferred to build spec
- Site display: no frontend changes
- `senator.cpf`: deferred to TSE transform spec (spec 2)
- LGPD enforcement at the build layer: `cpf` must be excluded from `{id}.json` — enforced in the build spec
