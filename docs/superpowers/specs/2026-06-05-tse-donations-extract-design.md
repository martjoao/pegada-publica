# TSE Donations Extract — Design

**Date:** 2026-06-05
**Status:** approved

---

## Overview

Add an `extract/tse/` module that downloads two bulk file families from the TSE
open-data portal for elections 2018 and 2022. This is a pure extract: files are
saved verbatim as raw artifacts; all filtering and linking is a transform concern.

**Scope:** federal candidates only — `DS_CARGO` ∈ `{DEPUTADO FEDERAL, SENADOR,
PRESIDENTE}`. State and municipal candidates are out of scope for now; a future
expansion (Approach B) will add them distinguished by office type.

**Prerequisite:** A separate bio-detail extract spec (not this one) will add CPF
fetching for deputies (`GET /deputados/{id}`) and senators. The transform step that
links TSE candidate records to our `deputy`/`senator` entities depends on both that
spec and this one being complete.

---

## Data Sources

### 1. `receitas_candidatos` — Donation records

One ZIP per election year from the TSE open-data portal. Each ZIP contains one or
more CSVs (national file or per-state files) with all campaign donation records
nationwide. Key fields (to be verified against actual file header per the open item
in `decisions.md`):

- `DS_ELEICAO`, `DS_CARGO` — election and office
- `NM_CANDIDATO`, `SG_PARTIDO`, `SG_UF` — candidate identity
- `NM_DOADOR`, `NM_DOADOR_RFB`, `NR_CPF_CNPJ_DOADOR` — donor identity
- `VR_RECEITA` — donation amount
- `DS_ORIGEM_RECEITA` — funding source type (individual, party transfer, self-funding, etc.)
- `DT_RECEITA` — donation date

**All funding source types are extracted** (individual donations, party transfers,
self-funding, institutional). Filtering to specific types is a transform concern.

### 2. `consulta_cand` — Candidate registry

One ZIP per election year with candidate metadata. Key field: `NR_CPF_CANDIDATO`,
used in transform to link TSE candidates to our `deputy`/`senator` entities.

---

## Components

### New files

**`etl/extract/tse/receitas.py`**
Downloads `receitas_candidatos` ZIPs for 2018 and 2022, writes a manifest JSON
alongside each ZIP. Follows the same `run(client, years, out_dir)` injectable-
dependency pattern as existing extract scripts.

**`etl/extract/tse/candidatos.py`**
Same pattern for `consulta_cand` ZIPs.

**`etl/common/http_client.py`** — add `TseDownloader` class
Handles large binary downloads differently from `CamaraClient`/`SenadoClient`:
- `download(url, dest_path) -> None`
- `stream=True`, chunk-based write to a sibling temp file, atomic rename on success
- Same retry/backoff logic as existing clients (5xx, timeout, connection error)
- 4xx raises immediately (not retryable)
- Content-length mismatch after download: raise and delete temp file

**`etl/common/paths.py`** — add four helpers:
- `tse_receitas_zip_path(year)` → `data/raw/tse/receitas/{year}.zip`
- `tse_receitas_manifest_path(year)` → `data/raw/tse/receitas/{year}_manifest.json`
- `tse_candidatos_zip_path(year)` → `data/raw/tse/candidatos/{year}.zip`
- `tse_candidatos_manifest_path(year)` → `data/raw/tse/candidatos/{year}_manifest.json`

### Test files

- `etl/tests/test_tse_downloader.py`
- `etl/tests/test_tse_receitas_extract.py`
- `etl/tests/test_tse_candidatos_extract.py`

No `__init__.py` files — namespace packages per decision 002.

---

## Data Flow

For each year in `(2018, 2022)`:

1. **Download** — `TseDownloader.download(url, dest_zip_path)` streams to temp file,
   renames to final path atomically on success.

2. **Inventory** — open the downloaded ZIP with `zipfile.ZipFile`. TSE ZIPs may
   contain one national CSV or multiple per-state CSVs; handle both. For each CSV:
   - Read header row → column name list
   - Count total rows (line-by-line, never loading full file into memory)
   - For `receitas`: count rows where `DS_CARGO` ∈ federal office set
   - For `candidatos`: count rows where `DS_CARGO` ∈ federal office set

3. **Manifest** — write JSON alongside the ZIP:
   ```json
   {
     "_meta": {
       "source": "tse-dados-abertos",
       "source_url": "https://...",
       "fetched_at": "2026-06-05T12:00:00Z",
       "encoding": "latin-1"
     },
     "files": [
       {
         "filename": "receitas_candidatos_2022_BRASIL.csv",
         "columns": ["DS_ELEICAO", "DS_CARGO", "NM_CANDIDATO", "..."],
         "total_rows": 1234567,
         "federal_rows": 89012
       }
     ]
   }
   ```

**Encoding:** TSE files are commonly ISO-8859-1 (latin-1). The manifest records the
assumed encoding; the transform step must open CSVs with the same encoding.

**TSE URLs** are defined as module-level constants in each extract script
(e.g. `RECEITAS_URLS = {2018: "...", 2022: "..."}`). Exact URLs must be verified
against the TSE open-data portal at implementation time — not assumed from memory.

---

## LGPD Constraints

### Extract layer
No constraint. `data/raw/tse/` is gitignored and not published. The files are
already public government data.

### Transform and build layers

| Field | Rule |
|---|---|
| `NR_CPF_CNPJ_DOADOR` (donor CPF) | Store in DB for cross-referencing only. **Never surface to end users in any form.** Legal basis: LGPD Art. 7 IX (legitimate interest for social control), same as CPF×QSA feature. |
| `NM_DOADOR` / `NM_DOADOR_RFB` (donor name) | Can be displayed. Donors to political campaigns are public actors under LGPD Art. 7 IX. Show name + city, never CPF. |
| `NR_CPF_CANDIDATO` (candidate CPF) | Internal use only — linking TSE records to `deputy`/`senator` entities. Not displayed. |
| Party transfers (`DS_ORIGEM_RECEITA = "Recursos de partidos"`) | No CPF. Can be aggregated and displayed freely. |
| Self-funding | Candidate's own CPF — same rule as `NR_CPF_CANDIDATO`: link use only, not displayed. |

### Display tiers by recipient type

- **Elected deputies/senators** — individual donation breakdown on their page (donor
  name + amount, no CPF).
- **Non-elected federal candidates** — no individual pages. Donations surface as
  party-level aggregates only (e.g. on a donor page: "donated R$X to losing PT
  federal candidates").
- **Presidential candidates (any result)** — full donor detail may be shown (name,
  city, amount, party). Presidential campaign finance is the highest-scrutiny context;
  all candidates are public figures; full disclosure is in the public interest.

The confidence-tier rule from `CLAUDE.md` applies: any derived or aggregated value
is labeled as computed, not a direct government record.

---

## Error Handling

**`TseDownloader`:**
- 5xx / timeout / `ConnectionError` → retry with exponential backoff
- 4xx → raise immediately
- Content-length mismatch → raise, delete temp file

**Extract scripts:**
- ZIP corruption → raise with path (operator re-downloads)
- Expected CSV not found in ZIP → raise listing actual filenames (ZIP structure may
  change between TSE releases)
- CSV encoding failure → raise with encoding assumption noted (`latin-1`)

---

## Testing

TDD convention: raw PT inputs, canonical-EN or structural assertions. All tests use
injectable dependencies (`TseDownloader`, `out_dir`) for isolation.

**`test_tse_downloader.py`:**
- Successful download writes correct bytes and renames atomically
- Temp file cleaned up on failure
- Retries on 503 and `ConnectionError`; raises immediately on 404
- Content-length mismatch raises and leaves no partial file

**`test_tse_receitas_extract.py`** / **`test_tse_candidatos_extract.py`:**
Use a mock `TseDownloader` that writes a small in-memory fake ZIP (with a sample CSV)
to the destination path:
- Manifest written with correct `_meta` fields
- `columns` list matches CSV header
- `total_rows` and `federal_rows` counted correctly (raw PT `DS_CARGO` values as
  inputs; correct counts as assertions)
- Multi-file ZIP (per-state CSVs): manifest lists all files, counts per file
- `run()` accepts injectable `downloader` and `out_dir`

---

## Out of Scope (this spec)

- **Bio-detail CPF extract** for deputies and senators — separate spec, prerequisite
  for the transform linking step.
- **Transform step** — linking TSE donors/candidates to `deputy`/`senator` entities,
  writing to `pegada.db`.
- **State and municipal candidates** — future scope (Approach B), will distinguish
  `DS_CARGO` for governor, state assembly, etc.
- **CPF×QSA cross-reference** — separate feature, depends on both this extract and
  the Receita Federal QSA extract.
