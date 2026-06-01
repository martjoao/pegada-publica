# Senado Senators Pipeline — Design

**Date:** 2026-06-01
**Status:** Approved
**Stage:** ETL (extract + transform) → build → site (the full pipeline, mirroring deputies)

## Goal

Replicate the existing deputy pipeline for **senators** (Senado Federal), end to end:
extract → transform → build → site. Mirror every established convention (folder
layout, provenance wrapper, canonical-English transform, per-entity JSON build,
Astro + React-island site). Keep the deputy pipeline and all its tests intact.

This doc captures the **live API probe findings** (the Senado API differs materially
from Câmara) and the resulting senator data model.

## API findings (probed live 2026-06-01)

Base URL: `https://legis.senado.leg.br/dadosabertos`. Returns **XML by default**;
every endpoint we need **honors `Accept: application/json`** (verified: HTTP 200,
`content-type: application/json`). So we stay JSON — no XML parsing.

**Quirk:** the Senado JSON is a 1:1 transcription of XML, so single-child elements
come back as a **dict, not a list** (a `<Filiacao>` with one entry is an object,
not a one-element array). Probed cases happened to return lists, but this is a
documented Senado footgun — the extract/transform must coerce "maybe-list" nodes.

### Endpoints used

| Endpoint | Carries | Notes |
|---|---|---|
| `/senador/lista/legislatura/{n}` | roster for a legislature | **245** entries each for 56 and 57 (all who held a seat that term: titulares + suplentes who took office). Slim: `IdentificacaoParlamentar` + `Mandatos`. |
| `/senador/lista/atual` | the **81** senators currently in exercise | Used to derive `current_status = in_office`. Rich (mandate, suplentes, exercicios). |
| `/senador/{cod}/mandatos` | per-senator mandates with dated **exercicios** | The office-period source. Each `Exercicio` has `DataInicio`, optional `DataFim` + `DescricaoCausaAfastamento`. |
| `/senador/{cod}/filiacoes` | dated party affiliation history | `DataFiliacao` / `DataDesfiliacao` per party. The party-at-vote-time source. |

Top-level JSON keys (each wraps a `Metadados` + `Parlamentar(es)` payload):
`ListaParlamentarLegislatura`, `ListaParlamentarEmExercicio`, `MandatoParlamentar`,
`FiliacaoParlamentar`.

### Domain differences from deputies (and how we model them)

- **8-year terms across two legislatures.** A `Mandato` carries
  `PrimeiraLegislaturaDoMandato` and `SegundaLegislaturaDoMandato` (e.g. 57ª
  2023–2027 **and** 58ª 2027–2031). 81 seats, 3 per state, elected in halves
  (2018 cohort → 2019–2027; 2022 cohort → 2023–2031). We model one `senate_term`
  row **per legislature the mandate covers** (so a mandate beginning in 57ª yields
  rows for 57 and 58), capturing UF and `condition`.
- **Suplentes (alternates).** `Mandato.DescricaoParticipacao` is the condition:
  `Titular` / `1º Suplente` / `2º Suplente`. We map any `… Suplente` → `alternate`,
  `Titular` → `titular` (same axis as the deputy `condition`). Suplentes who never
  took office have empty `Exercicios` → zero office periods (modeled, like a deputy
  who never assumed). The explicit titular↔suplente *link* is **deferred** (the
  `Mandato.Suplentes`/`Titular` block carries it, but it's a narrative feature; see
  decisions ledger deferral).
- **Office periods from exercicios, not a history event stream.** Câmara folds a
  `/historico` event list; the Senado gives the intervals **directly** as
  `Exercicio` rows (`DataInicio`/`DataFim`). So the Senado interval builder is a
  straight map (sort + close-with-DataFim), not a fold. A still-open exercicio
  (`DataFim` absent) is an open interval, capped at the legislature end like deputies.
- **Party affiliation from `/filiacoes`.** Dated directly (`DataFiliacao` →
  `DataDesfiliacao`), so again a map, not a fold. *Caveat:* `/filiacoes` reflects
  the senator's party-registration history, which may predate or not perfectly align
  with the senate term; we keep it verbatim (it's the authoritative party-at-date
  source). We do not split by legislature (the Senado party data is continuous, not
  per-term like Câmara's `/historico`).

### `current_status` mapping (Senado → canonical EN)

Câmara's enum is `in_office | substitute | on_leave | suspended | vacated |
term_ended | null`. The Senado does not expose a single equivalent field, so we
derive it:

- In `/senador/lista/atual` → **`in_office`**.
- Not in `atual`, but has a mandate covering a current legislature, latest exercicio
  closed by a leave-type cause (`LIC*`/`AFO`/`LCS` …) → **`on_leave`**.
- Not in `atual`, latest exercicio closed by `RET` (titular returned) and the
  senator is a suplente → **`substitute`**.
- Mandate covers only past legislatures (no current-term coverage) → **`term_ended`**.
- Has a mandate row but never any exercicio → **`null`** (never assumed).

`suspended` / `vacated` have no clean Senado signal in these endpoints; they stay in
the enum (shared with deputies) but are not currently produced for senators. This is
documented in the glossary and the decisions ledger.

## Schema shape — parallel senator tables

DEFAULT (lowest-risk) path per the mandate: **parallel tables** in the same
`pegada.db`, mirroring the deputy tables, so the working deputy pipeline is
untouched. A unified `parliamentarian` model is recorded as a **deferral**.

```
senator(id PK, name, photo_url, current_status)
senate_term(senator_id, legislature, state, condition, PRIMARY KEY(senator_id, legislature))
senator_office_period(senator_id, legislature, condition, start_at, end_at, cause, PK(senator_id,start_at))
senator_party_affiliation(senator_id, party, start_at, end_at, source_note, PK(senator_id,start_at))
senator_name_history(senator_id, name, start_at, end_at, PK(senator_id,start_at))
source  (shared audit table; already exists)
```

`id` = `CodigoParlamentar` (stable Senado id; the page URL key — mirrors decision
006). ISO-8601 TEXT dates; `end_at IS NULL` = open interval (mirrors deputy schema).
Senado dates are date-only (`YYYY-MM-DD`) — kept verbatim; they still sort and
compare correctly against the `T00:00` legislature bounds.

`senate_term` replaces the deputy `mandate`+adds `condition` (deputies carry
`condition` on `office_period`; senators carry it on the term too, since the Senado
gives it at mandate granularity and a suplente may never have an office period).
`name_history` is included for parity though the Senado rarely changes parliamentary
names — it degenerates to a single open interval from the roster name.

## Components (mirror the deputy modules)

- `etl/common/http_client.py` — add **`SenadoClient`** (JSON via `Accept` header, same
  retry/backoff; **no** `links`-pagination — Senado returns whole payloads — and a
  `get(path)` that returns the parsed dict). `CamaraClient` is untouched.
- `etl/common/paths.py` — add `senado_lista_path(legislatura)`,
  `senado_mandatos_path(cod)`, `senado_filiacoes_path(cod)` under
  `data/raw/senado/{lista,mandatos,filiacoes}/`.
- `etl/common/senado_json.py` — tiny helper `as_list(node)` coercing the
  dict-or-list quirk; `unwrap(payload, *keys)` to dig through the verbose envelope.
- `etl/extract/senado/lista.py` — fetch `lista/legislatura/{56,57}` → one landing
  file each (provenance-wrapped, raw verbatim).
- `etl/extract/senado/detalhe.py` — resumable/fault-tolerant per-senator crawl of
  `/mandatos` and `/filiacoes` (mirrors `historico.py`: `skip_existing`, per-item
  try/except, logs failed ids).
- `etl/transform/senado_intervals.py` — pure builders:
  `office_periods(mandatos)`, `party_affiliations(filiacoes)`,
  `senate_terms(mandatos)`, `current_status(...)`. Raw PT → canonical EN here.
- `etl/transform/db.py` — append the 5 senator tables to the schema (deputy tables
  unchanged; full rebuild still drops/recreates everything).
- `etl/transform/senado/senadores.py` — orchestrator (full rebuild), mirroring
  `transform/camara/deputados.py`.
- `build/senadores.py` — DB→JSON, `senadores/{id}.json` + slim `index.json`,
  accent-insensitive A–Z sort; reads DB via SQL only (no `etl` import).
- `site/src/pages/senadores/[id].astro`, `site/src/pages/senadores/index.astro`,
  `site/src/components/SenatorDirectory.tsx`, `site/src/lib/data.ts` (+ loaders),
  reusing `labels.ts`/`types.ts`. Nav link added in `Base.astro`.

## Output file formats

Extract landing files: same provenance wrapper as deputies (`_meta` + raw `dados`).
Build JSON: same shape as the deputy `{id}.json` / `index.json`, with senator fields.

## Testing (TDD, strict)

- HTTP client: `SenadoClient` JSON GET, retry, client-error no-retry (mocked
  `responses`).
- paths: the three new path helpers.
- senado_json: `as_list` on dict/list/None; `unwrap`.
- intervals: office periods (open + closed-by-DataFim + cap at term end), party
  affiliations (open + closed), senate_terms across two legislatures, current_status
  (in_office / on_leave / substitute / term_ended / null). Raw PT in → canonical EN out.
- transform: end-to-end raw→DB, dedup across the two legislature files, party-at-date
  query, idempotency. Plus: deputy tables still build (regression).
- build: per-senator detail + slim sorted index, every status branch.

## Out of scope / deferred

- Unified `parliamentarian` model (deferral — see ledger).
- Explicit titular↔suplente substitution link (deferral — the data is in
  `Mandato.Suplentes`).
- `suspended`/`vacated` detection for senators (no clean signal in these endpoints).
- Votes, speeches, committees, expenses — later sources.
