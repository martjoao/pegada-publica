# Canonical Deputy Schema — Design

**Date:** 2026-05-31
**Status:** Approved (design) — implementation pending
**Stage:** ETL `transform` (which, for now, also performs `load` — see Decisions)

## Purpose

Turn the raw Câmara landing files (the deputy roster + per-deputy history) into a
clean, deduplicated, **canonical** deputy model in a local database — the
system-of-record the later `build` stage reads to produce the static site.

The defining requirement is the project's party-migration constraint: votes must
be attributed to the party a deputy held **at the time of the vote**. This schema
makes that a single interval lookup.

## Scope

**In scope**

- Identity resolution: collapse the raw roster to one row per Câmara deputy `id`,
  unified across the 56ª and 57ª legislaturas.
- Dated **party-affiliation** timeline (from historico).
- Dated **in-office (exercise)** timeline, covering titulares *and* serving
  suplentes (from historico).
- **Name history** timeline (from historico).
- Provenance/audit of what was ingested.

**Out of scope (see Deferrals)**

- Explicit titular↔suplente substitution *link*.
- Biographical/detail fields (cpf, nomeCivil, dataNascimento, escolaridade, redes).
- Party as a first-class entity (normalizing `sigla_partido` → a party id).
- Bills, votes, expenses, amendments, TSE/RF cross-reference.

## Data sources (both confirmed live, 2026-05-31)

| Source | Endpoint | Role |
|---|---|---|
| Câmara dados abertos | `GET /deputados?idLegislatura={56,57}` | Enumerate ids; seed `deputado` + `mandato`. Already extracted. |
| Câmara dados abertos | `GET /deputados/{id}/historico` | Build party / exercise / name timelines. **New extract.** |

Key confirmed facts about `/historico`:

- Takes **no query parameters** (rejects `idLegislatura`, date ranges, `itens`
  with HTTP 400). One param-less call returns the deputy's full cross-term history,
  unpaginated (`links` has only `self`).
- Each entry carries: `siglaPartido`, `siglaUf`, `urlFoto`, `nome`, `idLegislatura`,
  `dataHora` (ISO timestamp), `situacao`, `condicaoEleitoral`, `descricaoStatus`.
- `situacao` ∈ {`Exercício` (in office), `Licença` (titular on leave),
  `Suplência` (suplente stepped down), `Convocado` (transient call-up — ignore),
  `Fim de Mandato`}.
- `condicaoEleitoral` ∈ {`Titular`, `Suplente`}, **stable per person**.
- Serving suplentes are first-class deputies with their own `id` and full historico
  (this is why a legislatura roster has >513 unique ids).

## Schema (SQLite)

Datetimes are stored as ISO-8601 **TEXT** (SQLite has no datetime type; ISO-8601
sorts correctly lexicographically). `end_at IS NULL` denotes an open/current interval.

```sql
-- identity: one row per unique Câmara deputy id (stable across terms & name changes)
CREATE TABLE deputado (
  id        INTEGER PRIMARY KEY,      -- Câmara id; also the page URL key (/deputado/{id})
  nome      TEXT NOT NULL,            -- current/latest parliamentary name (for display)
  foto_url  TEXT
);

-- terms served + state represented that term
CREATE TABLE mandato (
  deputy_id    INTEGER NOT NULL REFERENCES deputado(id),
  legislatura  INTEGER NOT NULL,      -- 56 | 57
  uf           TEXT NOT NULL,         -- e.g. "MA"
  PRIMARY KEY (deputy_id, legislatura)
);

-- dated IN-OFFICE intervals — covers titulares AND serving suplentes
CREATE TABLE exercicio (
  deputy_id    INTEGER NOT NULL REFERENCES deputado(id),
  legislatura  INTEGER NOT NULL,
  condicao     TEXT NOT NULL,         -- "Titular" | "Suplente"
  start_at     TEXT NOT NULL,         -- ISO 8601
  end_at       TEXT,                  -- NULL = currently in office
  PRIMARY KEY (deputy_id, start_at)
);

-- dated PARTY affiliation timeline — independent of exercicio
CREATE TABLE party_membership (
  deputy_id        INTEGER NOT NULL REFERENCES deputado(id),
  sigla_partido    TEXT NOT NULL,     -- e.g. "PP"
  start_at         TEXT NOT NULL,     -- ISO 8601
  end_at           TEXT,              -- NULL = current
  legislatura      INTEGER NOT NULL,
  descricao_origem TEXT,              -- the source descricaoStatus breadcrumb
  PRIMARY KEY (deputy_id, start_at)
);

-- dated PARLIAMENTARY-NAME timeline
CREATE TABLE name_history (
  deputy_id INTEGER NOT NULL REFERENCES deputado(id),
  nome      TEXT NOT NULL,
  start_at  TEXT NOT NULL,            -- ISO 8601
  end_at    TEXT,                     -- NULL = current
  PRIMARY KEY (deputy_id, start_at)
);

-- audit: one row per ingested raw landing file (fields nullable — minimal _meta tolerated)
CREATE TABLE source_meta (
  source       TEXT,                  -- "camara-dados-abertos"
  endpoint     TEXT,                  -- "/deputados" | "/deputados/{id}/historico"
  legislatura  INTEGER,
  fetched_at   TEXT,
  record_count INTEGER
);
```

`exercicio` and `party_membership` are kept **orthogonal** because they move
independently — a titular on leave keeps their party affiliation.

### URL key

The canonical page URL is **`/deputado/{id}`**. The Câmara `id` is the stable
resolution key — unique by construction, immune to name changes, and requiring no
slug-generation logic. The human-readable label (current `nome`) is shown on the
page, not in the URL.

## Transform logic

1. **Identity / dedup.** Read both `data/raw/camara/deputados/legislatura-{56,57}.json`.
   Collapse all rows to one `deputado` per `id` (the raw roster has duplicate rows
   per id — one per party affiliation and per name variant). Insert one `mandato`
   row per (id, legislatura) with that term's `uf`.
2. **Per-deputy historico.** For each id, read its historico landing file and build
   three interval sets by ordering entries on `dataHora`:
   - **Party intervals:** each `"…início da legislatura"` or `"Alteração de partido"`
     entry opens an interval at that `siglaPartido`; close it at the next
     party-changing entry (or term end, or NULL if open).
   - **Exercise intervals:** each `situacao == "Exercício"` entry (descricaoStatus
     `"Entrada - …"`) opens an interval tagged with its `condicaoEleitoral`; close it
     at the next entry that takes the deputy out of exercise — a `"Saída - …"` entry,
     i.e. `situacao` ∈ {`Licença` (titular leave), `Suplência` (suplente step-down),
     `Fim de Mandato`}; **ignore transient `"Convocado"` entries**.
   - **Name intervals:** each entry whose `nome` differs from the running value
     opens a new name interval.
   - A final interval with no closing entry stays **open** (`end_at = NULL`, i.e.
     ongoing as of the fetch); past terms close on their explicit `Fim de Mandato`
     / `Saída` entry. (Legislatura bounds, for reference: 56ª ends `2023-01-31`,
     57ª ends `2027-01-31`.)
3. **Upsert** all rows into SQLite (idempotent — re-running re-derives the same data).
4. Record one `source_meta` row per ingested raw file.

## Key queries enabled

```sql
-- party at vote time (the core constraint)
SELECT sigla_partido FROM party_membership
WHERE deputy_id = :id AND :vote_ts >= start_at AND (:vote_ts < end_at OR end_at IS NULL);

-- was this deputy actually in office at time T?
SELECT condicao FROM exercicio
WHERE deputy_id = :id AND :ts >= start_at AND (:ts < end_at OR end_at IS NULL);
```

## Provenance & confidence

`source_meta` makes the DB self-auditing (what was fetched, when, how many records).
All entity rows trace to `camara-dados-abertos`.

**No confidence tier applies to this schema** — `party_membership`, `exercicio`,
and `name_history` are *direct* government records, not inference. Confidence tiers
are reserved for derived/inferred data (the CPF×QSA cross-reference, and — when
built — the substitution link).

## Testing strategy

TDD, with fixtures built from the **real** historico captured during design, so
tests assert against known-correct intervals:

- **Suplente exercise** (Allan Garcês, id 226708): his `Exercício` intervals must
  match André Fufuca's leave windows; `condicao == "Suplente"` throughout.
- **Party migration** (Adail Filho 220714, Alexandre Guimarães 220542, Alfredo
  Gaspar 220576): two dated party intervals each, switch at the known `dataHora`.
- **Name history** (Garcês): `[Allan Garcês → Dr. Allan Garcês @ 2024-07-18]`.
- **Dedup:** 870 raw rows (57ª) collapse to 642 `deputado` rows.

## Decisions

See `docs/decisions.md` for the running ledger. Decisions specific to this design:

- **D1 — Model dated party membership now**, populated from list + a new historico
  extract (rather than per-term party *sets* deferred for later rework). Historico
  is cheap (one param-less call/id), so there is no reason to ship the lossy version.
- **D2 — Transform writes straight to a local DB** (merging `transform`+`load` for
  now), engine **SQLite**, with **DuckDB deferred** as a read/analytics layer for
  the later CPF×QSA joins (DuckDB can `ATTACH` a SQLite file, so this is not a lock-in).
- **D3 — Approach A (normalized, pre-computed intervals)** over flatter or
  event-sourced alternatives: the vote-attribution query is a direct interval lookup,
  and interval-folding belongs in transform, not in every consumer.
- **D4 — `exercicio` + `party_membership` kept orthogonal** (two timelines).
- **D5 — Include name history now** (cheap, same source, real test case exists).
  Serves historical accuracy and search-by-former-name.
- **D6 — Page URL key = Câmara `id`** (`/deputado/{id}`), not a name slug — stable,
  unique by construction, immune to name changes, no slug logic needed.

## Deferrals

See `docs/decisions.md` for the authoritative list. Summary:

- **Substitution link (titular↔suplente).** Not in scope. `exercicio` already
  answers "who held the seat at time T", so the explicit link is a *narrative*
  feature, not a data-integrity one. Doing it honestly needs the TSE candidate
  dataset (suplente ordering) — see ledger for the full requirements and the
  coligação caveat.
- **Bio/detail fields** — need the `/deputados/{id}` detail fetch.
- **Party as an entity** — its own brainstorm.
