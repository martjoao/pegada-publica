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

---

## Deferrals

Work intentionally not done yet. Each: what, why deferred, and **what it takes to
undefer**.

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
