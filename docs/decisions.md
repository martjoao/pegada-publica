# Decisions & Deferrals

A running ledger of consequential project decisions, deferred work (with what it
would take to undefer), and open items. **Decisions are numbered chronologically
(`001` = oldest)** so numeric/alphabetical order matches the order they were made;
append new ones with the next number. Deferrals and open items are living lists.
Detailed designs live under `docs/superpowers/specs/`.

---

## Decisions

Each decision: what was decided, why, and (implicitly) when, by its index. Mark
**superseded** rather than deleting, so the history stays readable.

**001 — First extract = Câmara deputy roster.** `/deputados` for legislaturas 56 &
57, written as provenance-wrapped raw JSON landing files; data is gitignored, only
code committed.
→ spec: `docs/superpowers/specs/2026-05-31-camara-deputados-extract-design.md`

**002 — ETL organized by phase.** `common/`, `extract/`, `transform/` (load folded
into transform for now), using PEP 420 namespace packages (no `__init__.py`). pip +
requirements.txt.

**003 — Canonical deputy schema = Approach A (normalized, pre-computed intervals).**
Tables: `deputado`, `mandato`, `exercicio`, `party_membership`, `name_history`,
`source_meta`. Two orthogonal dated timelines (party affiliation vs. in-office
exercise), each derived by folding the `/historico` event stream into intervals.
*Why:* the party-at-vote-time constraint becomes a single interval lookup; interval
logic belongs in transform, not in every consumer.
→ spec: `docs/superpowers/specs/2026-05-31-canonical-deputy-schema-design.md`

**004 — Model dated party membership now** (not per-term party sets). *Why:*
`/historico` is cheap (one param-less call per id), so there's no reason to ship a
lossy set-based version and rework it later.

**005 — Include parliamentary name history now.** *Why:* same source (`/historico`),
trivial extra interval table, and a real test case exists (Allan Garcês). Serves
historical accuracy and search-by-former-name.

**006 — Page URL key = Câmara `id`** (`/deputado/{id}`), not a name slug. *Why:*
stable and unique by construction; immune to name changes; no slug-generation logic.

**007 — Storage: SQLite as the system-of-record; `transform` writes straight to it**
(merging `transform`+`load` for now). *Why:* stdlib, transactional upserts suit
incremental ETL; the deputy roster is small and relational.

**008 — DuckDB deferred as a read/analytics layer**, to be introduced for the heavy
CPF×QSA cross-reference joins. *Why:* DuckDB reads CSV/Parquet natively and can
`ATTACH` a SQLite file, so choosing SQLite now is not a lock-in. Avoid maintaining
two writable stores — SQLite stores, DuckDB only reads.

**009 — Deputy page structure approved** (visual companion): header, party-migration
timeline, mandate/exercise, then future placeholder sections. URL `/deputado/{id}`.

**010 — Build stage (deputies) = per-deputy detail JSON + slim directory index**,
generated from `pegada.db` by a top-level `/build` stage that reads the DB via SQL
(schema = the contract; no `etl` imports). Directory default = latest legislatura +
`em_exercício` toggle (≈513) with `em exercício` / `suplente` / `licenciado` status
badges; ordering Nome A–Z (objective).
→ spec: `docs/superpowers/specs/2026-05-31-build-stage-deputies-design.md`

**011 — Milestone: canonical pipeline ran end-to-end on live data.** Extract (924
deputies) → transform → `pegada.db`. 14 transient 504 failures recovered on retry
(full coverage). Sanity check passed: "currently in exercise" = **514 ≈ 513** seats,
validating the exercise-interval logic. Counts: deputado 924, mandato 1255, exercicio
2339, party_membership 3009, name_history 1360.

**012 — Exercise intervals key on `situacao`, not `descricaoStatus`.** A loss of
mandate is filed as `situacao "Vacância"` with a `"Diverso - … Perda de Mandato"`
description (no `"Saída -"` prefix), so the old text-prefix close-rule left two 56ª
deputies (Valdevan Noventa, Manuel Marcos) showing as currently in exercise. Fixed to
close on any non-`Exercício`/`Convocado` state. Result is now **exact**: 57th-term
seats = **512 in exercise + 1 suspended (Glauber Braga) = 513**; DB matches the raw
`situacao` field with zero mismatches.

**013 — Canonical nomenclature = English; Portuguese only in the site display
layer.** Transform normalizes the raw PT API vocabulary to English identifiers (DB
tables/columns, build JSON keys, enumerated values); raw/extract stays PT verbatim.
Translation decisions are documented in `docs/glossario.md` (pointer in CLAUDE.md).
Folded in: `deputy.current_status` (from the latest settled situacao) so statuses are
accurate — `in_office` / `substitute` / `on_leave` / `suspended` / `vacated` /
`term_ended` — replacing the old condition-inferred guess (e.g. Glauber Braga is now
`suspended`, not mislabeled `licenciado`).

**014 — Frontend stack = Astro + React islands + Tailwind (SSG).** `/site` pre-renders
one static HTML page per bounded entity (deputies now) from the `build/output` JSON,
with React islands for interactivity (directory search + "Em exercício" toggle) and a
PT display layer (`src/lib/labels.ts`) mapping canonical EN codes → Portuguese. **Rule:**
pre-render bounded/named entities; push heavy/unbounded data (expenses, donations,
donors) into fetched JSON / aggregates / bulk downloads — never a page each (also LGPD).
React islands (not `.astro`) so components port if we ever go full SPA. Requires Node
20+ (system Node 10 is too old; nvm + Node 20 installed locally).

**015 — Deploy = produce data locally, build site in CI (Option A).** The ETL hits
flaky/heavy government APIs and is **not** CI-safe, so data is produced locally on each
source's schedule; the canonical `build/output` JSON is committed (it doubles as the
public open-data artifact), and a GitHub Action builds Astro + deploys to GitHub Pages
from that committed snapshot. *(Pending: un-ignore `build/output/` and add the Actions
workflow when we wire deployment.)*

**016 — Second parliamentarian = Senado senators, full pipeline.** Replicate the
deputy pipeline (extract→transform→build→site) for senators, mirroring every
convention. The Senado API was probed live before designing.
→ spec: `docs/superpowers/specs/2026-06-01-senado-senators-pipeline-design.md`

**017 — Senado API format = JSON via `Accept: application/json`.** The Senado API
returns XML by default but every endpoint we need honors the JSON Accept header
(verified live: 200 + `application/json`), so we stay JSON, no XML parsing. *Caveat:*
its JSON is a 1:1 XML transcription, so single-child nodes come back as a **dict, not
a list** — handled by an `as_list` coercion helper (`common/senado_json.py`).

**018 — Senado HTTP client = separate `SenadoClient`** (not a generalization of
`CamaraClient`). *Why:* the Senado returns whole payloads (no `links`/`next`
pagination) under a different base URL and envelope shape; a clean separate `get()`
is simpler than overloading the Câmara client and risks nothing for deputies.

**019 — Senator schema = parallel tables in the same `pegada.db`** (`senator`,
`senate_term`, `senator_office_period`, `senator_party_affiliation`,
`senator_name_history`); the shared `source` audit table is reused. *Why:* the
lowest-risk path mandated — the working deputy pipeline (and every deputy test) stays
untouched. Differences from deputies that the data forced: (a) **8-year mandates span
two legislatures** (`Primeira`/`SegundaLegislaturaDoMandato`), so one `senate_term`
row per covered legislature; (b) **`condition` lives on `senate_term`** (the Senado
gives Titular/Nº-Suplente at mandate granularity, and a suplente may have zero office
periods); (c) **office periods and party affiliations are read directly** from
`/mandatos` `Exercicio` rows and `/filiacoes` (dated intervals), not folded from an
event stream like Câmara `/historico` — so the Senado interval builders are maps, not
folds. `id` = `CodigoParlamentar` (stable; the page URL key, mirroring 006).

**020 — Senator `current_status` derived (no single Senado field).** `in_office` =
present in `/senador/lista/atual`; otherwise inferred from the latest exercicio's
`DescricaoCausaAfastamento` (leave-type → `on_leave`; titular-return `RET` for a
suplente → `substitute`) and mandate coverage (only past legislatures → `term_ended`;
a mandate with no exercicio → `null`). `suspended`/`vacated` have no clean signal in
these endpoints and are not produced for senators (the shared enum still carries them).

**021 — Milestone: senator pipeline ran end-to-end on live data.** Extract
(legislaturas 56 & 57 rosters → `__SENATOR_COUNT__` unique senators; per-senator
`/mandatos` + `/filiacoes` crawl) → transform → `pegada.db` → `build/senadores.py`.
Counts and the "≈81 currently in exercise" sanity check are recorded in the final
report; the build emits one `senadores/{id}.json` per senator plus a slim
`index.json`. *(Counts placeholder — replaced with live numbers after the run.)*

---

## Deferrals

Work intentionally not done yet. Each: what, why deferred, and **what it takes to
undefer**.

- **Unified `parliamentarian` model (deputies + senators in one entity set).**
  CLAUDE.md's core entity is "Parliamentarian — both houses", but the canonical
  schema is currently two parallel families (`deputy*` + `senator*`).
  *Why deferred:* unifying now risks the working deputy pipeline and every deputy
  test for no immediate gain; the two houses have genuinely different source shapes
  (Câmara event-stream `/historico` vs. Senado dated `/mandatos`+`/filiacoes`,
  4-year vs. 8-year terms, mandate-level vs. office-level condition).
  *To undefer:* introduce a `parliamentarian(id, house, …)` table with house-keyed
  ids and refactor both transforms to write a shared interval set; keep the
  house-specific extract/transform front-ends, converging only at the canonical
  boundary. Do it behind a green test suite for both houses.

- **Senator titular ↔ suplente substitution link.**
  *Why deferred:* same rationale as the deputy substitution-link deferral — it's a
  narrative feature, not data-integrity (`senator_office_period` already captures who
  held the seat when). *To undefer:* the Senado *does* carry the link structurally in
  `Mandato.Suplentes` / `Mandato.Titular` (CodigoParlamentar each way), so a
  `senate_substitution` table is a straight read — no TSE inference needed (unlike
  deputies). Add it when the relationship is surfaced on the page.

- **Senator `suspended` / `vacated` status.** The `/mandatos`+`/filiacoes`+`atual`
  endpoints expose no clean signal for these. *To undefer:* characterize the
  Senado afastamento-cause vocabulary (or an `afastamentos` endpoint) for
  suspension/loss-of-mandate causes and map them onto the canonical enum.

- **Substitution link (titular ↔ suplente).**
  *Why deferred:* `/historico` has no structured link (only an unreliable free-text
  mention in some `descricaoStatus` ofícios). `exercicio` already captures who held
  the seat when, so the explicit link is a narrative feature, not data-integrity.
  *To undefer well:* add the **TSE candidate dataset** extract (carries each party's
  suplente *ordering* per election) and match by CPF. *Caveat:* Brazil fills
  vacancies from the party/coligação list in order (not 1:1), and **2018/56ª used
  coligações** (suplente may be a different party than the titular), so pure
  same-party+UF+date inference is unreliable for the 56ª. A `substituicao` table
  would carry a **confidence tier** (`confirmed` = ofício names titular / `inferred`
  = unique temporal+party match / `ambiguous`).

- **Deputy bio/detail fields** (cpf, nomeCivil, dataNascimento, escolaridade, redes
  sociais, `ultimoStatus`).
  *Why deferred:* needs the per-deputy `GET /deputados/{id}` detail fetch, not yet
  built. *To undefer:* add a `extract/camara/deputado_detalhe` fetch and enrich
  `deputado` with nullable columns.

- **Party as a first-class entity** (normalize `sigla_partido` → a stable party id;
  party member history; mergers/renames).
  *Why deferred:* its own modeling problem. *To undefer:* its own brainstorm; the
  `uriPartido` in the roster carries a stable party id to anchor it.

- **Future deputy-page sections & site wiring.** Attendance, CEAP expenses, votes,
  bills, amendments, inferred corporate influence — added to `{id}.json` as their data
  sources land. Plus the `/site` frontend + deploy wiring (where `build/output/` is
  served from), and the party/proposition build outputs (own specs).

- **Other Câmara endpoints:** expenses (`/deputados/{id}/despesas`), committees
  (`/orgaos`), attendance (`/eventos`), speeches (`/discursos`), bills
  (`/proposicoes?autor={id}`), votes (`/votacoes/{id}/votos`).
  *Status:* `despesas` characterized (needs `ano`; exposes vendor `cnpjCpfFornecedor`).

- **Cross-source data:** TSE donations (bulk CSV), Receita Federal QSA (monthly full
  reload), Portal da Transparência amendments, and the signature **CPF×QSA inferred
  corporate influence** (with confidence tiers).

---

## Open verification items

Things believed-true but not yet confirmed end-to-end. Resolve before relying on them.

- **`/frentes`, `/profissoes`, `/ocupacoes`** — returned empty under a naive query;
  exact required params not yet confirmed.
- **TSE donations column names** — inferred from regulation/docs (e.g.
  `NR_CPF_CNPJ_DOADOR`), **not** yet verified against an actual file header / LEIA-ME.
- **`/despesas` full-extract volume** — confirmed ~480 docs/deputy/year; the larger
  "15M records" estimate from the probe was a multiplication error.
