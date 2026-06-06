# Pegada Pública — Claude Context

Open-source Brazilian congressional transparency portal. Aggregates public government data (Câmara, Senado, TSE, Receita Federal, Portal da Transparência) into a fully static website — no backend in production.

## Architecture

**Three stages, all run locally:**

1. **ETL** (`/etl`) — Python scripts that collect, process, and cross-reference data from official APIs and bulk dumps into a local database. Incremental where possible; Receita Federal requires full monthly reload.
2. **Static build** (`/build`) — pre-computes every page into individual JSON files (one per entity) plus listing/index files. No server-side rendering at request time.
3. **Static site** (`/site`) — frontend that fetches pre-generated JSON files. Hosted on GitHub Pages. Search runs in-browser.

**No backend API exists.** There is no runtime server. Every user interaction is a fetch() to a static JSON file.

## Status

- **Live:** https://martjoao.github.io/pegada-publica/ (public repo, GitHub Pages via
  Actions, Astro `base: /pegada-publica`). Every push to `main` rebuilds and redeploys.
- **Built:** deputy + senator pipelines end-to-end (parallel `deputy*` / `senator*`
  tables in one `etl/data/pegada.db`; a unified `parliamentarian` model is deferred).
- **TSE extract done:** `receitas_candidatos` + `consulta_cand` ZIPs for 2018 and 2022
  downloaded to `etl/data/raw/tse/` (gitignored). Transform step not yet built.
- **Bio extract done:** `extract/camara/bio.py` + `extract/senado/bio.py` crawled all
  924 deputies and 318 senators (decision 024). Raw files in `etl/data/raw/camara/bio/`
  and `etl/data/raw/senado/bio/` (gitignored). Deputy bio fields available: `nomeCivil`,
  `cpf`, `dataNascimento`, `escolaridade`, `redeSocial`, `urlWebsite`, `ultimoStatus`.
  **Transform done (decision 025):** nullable bio columns added to `deputy` and `senator`
  tables; `load_bio()` integrated into both transform scripts. Build wiring not yet done
  (`cpf` must be excluded from build JSON per LGPD).
- Consequential decisions & deferrals are logged in [`docs/decisions.md`](docs/decisions.md)
  (numbered ledger, 001 = oldest); EN↔PT term mappings in [`docs/glossario.md`](docs/glossario.md).

## Development

**Pipeline run order** (all local): extract → transform → build → site. The deputy
transform creates *all* canonical tables (incl. senator), so run it before the senator
transform on a fresh DB.

**Python (ETL + build)** — venv at `etl/.venv`, no global install:
- ETL tests:   `cd etl && .venv/bin/python -m pytest -q`
- Build tests: `cd build && PYTHONPATH=../etl ../etl/.venv/bin/python -m pytest -q`
- Build JSON:  `etl/.venv/bin/python build/deputados.py` / `build/senadores.py`

**Site** — requires Node 20 via nvm (system Node is too old):
`export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 20 && cd site && npm run build`
The site reads `build/output/*.json` from the filesystem at build time.

**Data refresh → deploy:** run ETL locally → rebuild `build/output` → **commit
`build/output`** (it's tracked, not ignored — it doubles as the open-data artifact) →
push to `main`; the GitHub Action builds and deploys to Pages automatically.

TDD is the standard (red→green→refactor); raw PT inputs, canonical-EN assertions.

## Naming

Raw government APIs are Portuguese, and the **extract** stage saves their payloads verbatim (PT). From **transform** onward, everything is normalized to **canonical English identifiers** (DB tables/columns, build JSON keys, enumerated values); Portuguese reappears only in the **site's display layer**. The canonical terms and their PT source/display mappings are defined in [`docs/glossario.md`](docs/glossario.md) — consult and update it whenever a term needs translating.

## Core Entities

- **Parliamentarian** — deputies and senators (both houses)
- **Party** — with full member history; party migrations tracked with start/end dates
- **Individual Donor (PF)** — linked to parties, parliamentarians, and companies
- **Company** — inferred influence derived by crossing TSE donor CPFs with RF QSA partner records
- **Bill/Proposition** — tagged, with full voting record
- **Amendment** — parliamentarian → municipality spending

## The Signature Feature

Corporate donations have been illegal since 2016. By crossing TSE donor CPFs with Receita Federal QSA partner lists, we reconstruct inferred corporate influence. This is always labeled with a confidence tier: **confirmed** (same CPF in both records), **historical** (pre-2016 donations), or **name-match only** (no CPF confirmation). Never presented as a finding of wrongdoing.

## Data Sources

| Source | Schedule |
|--------|----------|
| Câmara dos Deputados API | Daily (votes/attendance), weekly (expenses, bills) |
| Senado Federal API | Daily (votes/attendance), weekly (speeches) |
| TSE bulk download | After each election cycle |
| Receita Federal CNPJ dump | Monthly (full reload — no delta available) |
| Portal da Transparência | Weekly (amendments) |

## Scope

- Terms: 56ª (2019–2023) and 57ª (2023–present)
- Elections: 2018 and 2022

## Key Constraints

- **Static-only output**: the build step must produce everything the site needs. No server-side logic at request time.
- **Party migrations**: votes must always be attributed to the party the parliamentarian belonged to at the time of the vote, not their current party. This requires tracking party membership with date ranges.
- **LGPD compliance**: CPF cross-referencing is grounded in LGPD Art. 7 IX (legitimate interest for social control). Never expose raw CPFs to end users; use them only internally for matching.
- **Confidence tiers on derived data**: any value that results from inference (not direct government record) must carry a labeled confidence level.
- **No editorial bias**: entity ordering is always objective (alphabetical, chronological, or by a disclosed numeric metric). No scoring with ideological weight.
