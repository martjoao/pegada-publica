# Decisions & Deferrals

A running ledger of consequential project decisions, deferred work (with what it
would take to undefer), and open items. Newest entries first within each section.
Detailed designs live under `docs/superpowers/specs/`.

---

## Decisions

Each decision: what was decided, why, and when. Mark **superseded** rather than
deleting, so the history stays readable.

### 2026-05-31

- **Build stage (deputies) = per-deputy detail JSON + slim directory index**,
  generated from `pegada.db` by a top-level `/build` stage that reads the DB via SQL
  (schema = the contract; no `etl` imports). Directory default = latest legislatura +
  `em_exercício` toggle (≈513) with `em exercício` / `suplente` / `licenciado` status
  badges; ordering Nome A–Z (objective).
  → spec: `docs/superpowers/specs/2026-05-31-build-stage-deputies-design.md`

- **Deputy page structure approved** (visual companion): header, party-migration
  timeline, mandate/exercise, then future placeholder sections. URL `/deputado/{id}`.

- **Milestone — canonical pipeline ran end-to-end on live data.** Extract (924
  deputies) → transform → `pegada.db`. 14 transient 504 failures were recovered on
  retry (full coverage). Sanity check passed: "currently in exercise" = **514 ≈ 513**
  seats, validating the exercise-interval logic. Counts: deputado 924, mandato 1255,
  exercicio 2339, party_membership 3009, name_history 1360.

- **Canonical deputy schema = Approach A (normalized, pre-computed intervals).**
  Tables: `deputado`, `mandato`, `exercicio`, `party_membership`, `name_history`,
  `source_meta`. Two orthogonal dated timelines (party affiliation vs. in-office
  exercise), each derived by folding the `/historico` event stream into intervals.
  *Why:* the party-at-vote-time constraint becomes a single interval lookup; interval
  logic belongs in transform, not in every consumer.
  → spec: `docs/superpowers/specs/2026-05-31-canonical-deputy-schema-design.md`

- **Model dated party membership now** (not per-term party sets). *Why:* `/historico`
  is cheap (one param-less call per id), so there's no reason to ship a lossy
  set-based version and rework it later.

- **Include parliamentary name history now.** *Why:* same source (`/historico`),
  trivial extra interval table, and a real test case exists (Allan Garcês). Serves
  historical accuracy and search-by-former-name.

- **Page URL key = Câmara `id`** (`/deputado/{id}`), not a name slug. *Why:* stable
  and unique by construction; immune to name changes; no slug-generation logic.

- **Storage: SQLite as the system-of-record; `transform` writes straight to it**
  (merging `transform`+`load` for now). *Why:* stdlib, transactional upserts suit
  incremental ETL; the deputy roster is small and relational.

- **DuckDB deferred as a read/analytics layer**, to be introduced for the heavy
  CPF×QSA cross-reference joins. *Why:* DuckDB reads CSV/Parquet natively and can
  `ATTACH` a SQLite file, so choosing SQLite now is not a lock-in. Avoid maintaining
  two writable stores — SQLite stores, DuckDB only reads.

- **First extract = Câmara deputy roster** (`/deputados`, legislaturas 56 & 57),
  provenance-wrapped raw JSON landing files; data is gitignored, only code committed.
  → spec: `docs/superpowers/specs/2026-05-31-camara-deputados-extract-design.md`

- **ETL organized by phase** (`common/`, `extract/`; `transform/`/`load/` added when
  built) using PEP 420 namespace packages (no `__init__.py`). pip + requirements.txt.

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
