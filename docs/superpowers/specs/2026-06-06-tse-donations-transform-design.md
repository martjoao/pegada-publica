# TSE Donations Transform — Design

**Date:** 2026-06-06
**Status:** approved

---

## Overview

Add a `transform/tse/donations.py` module that reads the locally-downloaded TSE
bulk ZIPs (`consulta_cand` + `receitas_candidatos` for 2018 and 2022) and writes
three new canonical tables to `pegada.db`: `tse_candidate`, `donor`, and
`tse_donation`. The transform also backfills `senator.cpf` (deferred in decision
025), resolves `deputy_id`/`senator_id` FKs on `tse_candidate`, and produces two
build outputs: a donor ranking page (`donors_ranking.json`) and per-parliamentarian
`top_donors` arrays embedded in existing deputy/senator detail JSONs.

**Prerequisites:** bio extract complete (decisions 024–025); `deputy.cpf` already
populated; `senator.civil_name` already populated (used for CPF backfill matching).

---

## New DB tables

Added to `transform/db.py` SCHEMA. Full rebuild on each run (consistent with
existing pipeline); the `senator.cpf` backfill is an in-place UPDATE on an existing
table (safe to re-run since CPF was NULL before and the TSE source is stable).

### `tse_candidate`

One row per federal candidate per election year, loaded from `consulta_cand`.

```sql
CREATE TABLE tse_candidate (
  id              INTEGER PRIMARY KEY,
  election_year   INTEGER NOT NULL,
  office          TEXT NOT NULL,        -- federal_deputy | senator | president
  tse_seq         INTEGER NOT NULL,     -- SQ_CANDIDATO
  cpf             TEXT,                 -- NR_CPF_CANDIDATO; internal only (LGPD)
  name            TEXT NOT NULL,        -- NM_CANDIDATO
  party           TEXT NOT NULL,        -- SG_PARTIDO
  state           TEXT NOT NULL,        -- SG_UF
  election_result TEXT,                 -- elected | not_elected | alternate |
                                        --   invalidated | withdrew | pending | NULL
  deputy_id       INTEGER REFERENCES deputy(id),   -- nullable
  senator_id      INTEGER REFERENCES senator(id),  -- nullable
  UNIQUE(election_year, tse_seq)
);
```

### `donor`

One row per unique donor, deduplicated by `cpf_cnpj`.

```sql
CREATE TABLE donor (
  id         INTEGER PRIMARY KEY,
  cpf_cnpj   TEXT UNIQUE,  -- nullable (party transfers carry none); internal only (LGPD)
  name       TEXT NOT NULL, -- NM_DOADOR_RFB preferred, else NM_DOADOR
  city       TEXT,          -- NM_MUNICIPIO_DOADOR
  state      TEXT,          -- SG_UF_DOADOR
  donor_type TEXT           -- individual | company | party | unknown
);
```

`donor_type` is inferred from `cpf_cnpj` length: 11 digits → `individual`,
14 digits → `company`, NULL → `party`. Other lengths → `unknown`.

### `tse_donation`

One row per donation record from `receitas_candidatos`.

```sql
CREATE TABLE tse_donation (
  id                INTEGER PRIMARY KEY,
  election_year     INTEGER NOT NULL,
  tse_candidate_id  INTEGER NOT NULL REFERENCES tse_candidate(id),
  donor_id          INTEGER NOT NULL REFERENCES donor(id),
  amount            REAL NOT NULL,   -- VR_RECEITA parsed from BR decimal format
  date              TEXT,            -- DT_RECEITA as ISO-8601
  funding_source    TEXT,            -- see enum below
  receipt_number    TEXT,
  UNIQUE(election_year, receipt_number)  -- idempotent re-runs
);
```

---

## Canonical enum mappings

All canonicalization happens at the transform DB-write boundary (decision 013).
Add all new terms to `docs/glossario.md`.

### `office` (from `DS_CARGO`)

| Canonical | Source PT |
|---|---|
| `federal_deputy` | DEPUTADO FEDERAL |
| `senator` | SENADOR |
| `president` | PRESIDENTE |

### `election_result` (from `DS_SIT_TOT_TURNO`)

| Canonical | Source PT |
|---|---|
| `elected` | ELEITO, ELEITO POR QP, ELEITO POR MÉDIA, ELEITO NO 2º TURNO |
| `not_elected` | NÃO ELEITO, NÃO ELEITO (REJEIÇÃO DE CONTAS) |
| `alternate` | SUPLENTE |
| `invalidated` | CASSADO, DIPLOMA CASSADO |
| `withdrew` | RENÚNCIA, FALECIDO |
| `pending` | 2º TURNO (reached runoff; final result in a later round's row) |
| `NULL` | unknown / missing value |

### `funding_source` (from `DS_FONTE_RECEITA`)

| Canonical | Source PT |
|---|---|
| `individual_donation` | Doações de pessoas físicas |
| `self_funding` | Recursos do próprio candidato |
| `party_transfer` | Doações de partido / Transferências do partido |
| `electoral_fund` | Fundo Especial de Financiamento de Campanha (FEFC) |
| `party_fund` | Fundo Partidário |
| `candidate_transfer` | Recursos de outros candidatos |
| `other` | anything else (logged at WARNING level) |

---

## Transform pipeline

**Module:** `etl/transform/tse/donations.py`
**Run with:** `python -m transform.tse.donations`

Full rebuild each run. Four sequential steps:

### Step 1 — Load `tse_candidate` from `consulta_cand`

For each year (2018, 2022), open the ZIP and read all per-state CSVs (the
`consulta_cand` ZIPs have no BRASIL.csv — manifests show 29 per-state files for
2022). Filter rows where `DS_CARGO` ∈ `{DEPUTADO FEDERAL, SENADOR, PRESIDENTE}`.
Deduplicate to one row per `(AA_ELEICAO, SQ_CANDIDATO)` taking the highest
`NR_TURNO` — so a presidential candidate who reaches round 2 gets their final
`DS_SIT_TOT_TURNO`. Canonicalize `DS_CARGO` → `office` and `DS_SIT_TOT_TURNO`
→ `election_result`, then INSERT into `tse_candidate`.

### Step 2 — Backfill `senator.cpf` from `tse_candidate`

The Senado API does not expose CPFs (decision 025 deferral). The `consulta_cand`
data carries `NR_CPF_CANDIDATO` for all candidates including senators.

For every `tse_candidate` row where `office = 'senator'`: normalize both
`tse_candidate.name` and `senator.civil_name` (uppercase, strip accents, strip
punctuation), then exact-match. Skip senators whose `civil_name` is NULL (no
comparison possible). On match, `UPDATE senator SET cpf = tse_candidate.cpf`.

Matching uses `senator.civil_name` (not parliamentary name) since TSE
`NM_CANDIDATO` is the civil registration name. Unmatched rows log a WARNING —
not an error, since some senators ran before the 2018/2022 election scope. This
closes the `senator.cpf` deferral from decision 025.

### Step 3 — Resolve `deputy_id` / `senator_id` FKs on `tse_candidate`

```sql
UPDATE tse_candidate SET deputy_id = (
  SELECT id FROM deputy WHERE deputy.cpf = tse_candidate.cpf
)
WHERE office = 'federal_deputy' AND tse_candidate.cpf IS NOT NULL;

UPDATE tse_candidate SET senator_id = (
  SELECT id FROM senator WHERE senator.cpf = tse_candidate.cpf
)
WHERE office = 'senator' AND tse_candidate.cpf IS NOT NULL;
```

Presidential rows stay NULL. Deputies/senators whose CPF doesn't match our DB
(ran in 2018/2022 outside legislature 56/57 scope) also stay NULL — expected.

### Step 4 — Load `donor` + `tse_donation` from `receitas_candidatos`

For each year, open the ZIP and read **only the BRASIL.csv**
(`receitas_candidatos_{year}_BRASIL.csv`). The per-state CSVs are the same records
partitioned by UF — reading both would double-count all donations. If BRASIL.csv is
not found in the ZIP, raise `ValueError` (do not silently fall back to per-state
CSVs; the operator must investigate). Filter to
`DS_CARGO` ∈ federal set. For each row:

1. **Upsert `donor`** on `cpf_cnpj`: `INSERT OR IGNORE` — first-seen row wins for
   name/city/state. `donor_type` derived from `cpf_cnpj` length.
2. **Resolve `tse_candidate_id`** by `(election_year, SQ_CANDIDATO)`.
3. **Parse `VR_RECEITA`**: strip thousands separator `.`, replace decimal `,` with
   `.`, cast to `float`.
4. **INSERT `tse_donation`** with `ON CONFLICT(election_year, receipt_number) DO
   NOTHING` for idempotent re-runs.

---

## Build outputs

### New: `build/doadores.py` → `build/output/donors_ranking.json`

Ranks all donors by total amount across both elections. Emits the top 500. Each
entry includes the donor's full recipient list joined to `tse_candidate` for
name/party/state/result and to `deputy`/`senator` for the detail page link.

```json
{
  "generated_at": "2026-06-06T...",
  "total_donors": 12345,
  "donors": [
    {
      "rank": 1,
      "name": "João Silva",
      "city": "São Paulo",
      "state": "SP",
      "donor_type": "individual",
      "total_amount": 150000.00,
      "donations": [
        {
          "election_year": 2022,
          "candidate_name": "Maria Santos",
          "party": "PT",
          "state": "SP",
          "office": "federal_deputy",
          "election_result": "elected",
          "amount": 100000.00,
          "deputy_id": 123
        },
        {
          "election_year": 2018,
          "candidate_name": "Carlos Oliveira",
          "party": "PSDB",
          "state": "RJ",
          "office": "senator",
          "election_result": "not_elected",
          "amount": 50000.00,
          "senator_id": null
        }
      ]
    }
  ]
}
```

`deputy_id`/`senator_id` present and non-null = candidate has a detail page. The
site uses this to render linked vs. plain-text recipient names.

### Extended: `build/deputados.py` and `build/senadores.py`

Each parliamentarian JSON gains a `top_donors` array — top 20 donors by total
amount to that individual, across all elections:

```json
"top_donors": [
  {
    "name": "João Silva",
    "city": "São Paulo",
    "state": "SP",
    "donor_type": "individual",
    "total_amount": 50000.00,
    "elections": [2018, 2022]
  }
]
```

No CPF in any build output — display-safe by construction (LGPD).

### Site wiring (out of scope)

Rendering `donors_ranking.json` as a dedicated page and `top_donors` on
parliamentarian pages is a follow-on spec, consistent with how bio fields were
wired after their build spec (decision 026).

---

## LGPD constraints

| Field | Rule |
|---|---|
| `tse_candidate.cpf` | Internal only — used for FK resolution. Never emitted to build JSON. |
| `donor.cpf_cnpj` | Internal only — used for deduplication and future CPF×QSA cross-reference. Never emitted. |
| `donor.name` / `city` | Displayable — campaign donors are public actors under LGPD Art. 7 IX. |
| `senator.cpf` (backfilled) | Internal only — same rule as `deputy.cpf` (decision 025). |

---

## Testing

TDD convention: raw PT inputs, canonical-EN assertions. All tests use injectable
`db_path` and ZIP path dependencies.

**`etl/tests/test_tse_donations_transform.py`**

*Canonicalization helpers (pure functions, no DB):*
- `DS_CARGO` → `office`: all three values; unknown → raises
- `DS_SIT_TOT_TURNO` → `election_result`: `ELEITO POR QP` → `elected`,
  `SUPLENTE` → `alternate`, `2º TURNO` → `pending`, unknown → `None`
- `DS_FONTE_RECEITA` → `funding_source`: each mapped value; unknown → `other`
- `VR_RECEITA` decimal parsing: `"1.234,56"` → `1234.56`, `"0,00"` → `0.0`
- `cpf_cnpj` → `donor_type`: 11 digits → `individual`, 14 → `company`,
  `None`/empty → `party`

*`load_candidates()`:*
- Fake candidatos ZIP with two per-state CSVs (PT input rows) → correct
  `tse_candidate` count
- Deduplication on `(year, tse_seq)`: two rows for same candidate (round 1,
  round 2) → one row with round-2 `election_result`
- All three `office` values loaded correctly

*`backfill_senator_cpf()`:*
- Senator in DB with matching `civil_name` → `senator.cpf` updated
- No match → `senator.cpf` stays NULL, WARNING logged
- Accent/case normalization: `JOÃO SILVA` matches `João Silva`

*`load_donations()`:*
- Fake receitas ZIP with BRASIL.csv only → `donor` rows deduplicated by CPF
  (same donor on two rows → one `donor`, two `tse_donation`)
- Idempotent re-run: same `receipt_number` → no duplicate row
- `amount` parsed correctly from BR decimal format
- `tse_candidate_id` FK resolved from `SQ_CANDIDATO`

**`etl/tests/test_build_doadores.py`**
- Top-N ranking respects total amount order
- `deputy_id`/`senator_id` present and correct on linked recipients; `null` on
  unlinked candidates
- `top_donors` on a parliamentarian JSON contains correct aggregated totals, no
  CPF field present

---

## Glossario updates

Add to `docs/glossario.md`:

| Canonical (EN) | PT / source field | Meaning |
|---|---|---|
| `tse_candidate` | candidato TSE | A federal candidate in a TSE election year. |
| `donor` | doador | A unique campaign donor, deduplicated by CPF/CNPJ. |
| `tse_donation` | receita eleitoral | A single campaign donation record from TSE `receitas_candidatos`. |
| `office` | cargo / DS_CARGO | The elected office sought — `federal_deputy`, `senator`, or `president`. |
| `election_result` | DS_SIT_TOT_TURNO | Final election outcome for a candidate. |
| `funding_source` | DS_FONTE_RECEITA | Canonical source type for a donation. |
| `donor_type` | (derived) | `individual` (CPF, 11 digits), `company` (CNPJ, 14 digits), `party` (no CPF). |

---

## Out of scope (this spec)

- Site rendering of `donors_ranking.json` and `top_donors` — follow-on spec.
- Receita Federal QSA extract and the CPF×QSA corporate influence cross-reference.
- State and municipal candidates.
- `donor` detail pages (ruled out by decision 014 — no page per unbounded entity).
