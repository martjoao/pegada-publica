# Build Stage — Deputies (static JSON) — Design

**Date:** 2026-05-31
**Status:** Pages approved (deputy page + directory) — spec for review
**Stage:** `build` — reads `etl/data/pegada.db`, emits static JSON. No runtime server.

## Purpose

Pre-compute everything the site needs into individual static JSON files, straight
from the canonical SQLite DB. The static site fetches these files directly (GitHub
Pages); search and filtering run in-browser.

## Scope

**In:** deputies — a **detail file per deputy** and a **directory index**.

**Out (later):** party / proposition pages; and the future deputy-page sections
(attendance, CEAP expenses, votes, bills, amendments, inferred corporate
influence) — each emitted when its data source lands. The deputy detail file grows
new keys then; the directory index is stable.

## Outputs & layout

`build` is its own top-level stage (per the project architecture), **independent of
`etl`**: it reads the DB through SQL — the schema is the only contract, no `etl`
imports. Output is generated JSON (gitignored).

```
build/
  deputados.py          # orchestrator: DB -> JSON
  tests/
    test_deputados.py
build/output/           # generated, gitignored
  deputados/
    index.json          # slim cards for the directory + in-browser search
    {id}.json           # full per-deputy detail
```

Defaults (overridable): DB = `etl/data/pegada.db`; out = `build/output/`. Wiring the
output into the eventual `/site` deploy is deferred.

## JSON shapes

### `deputados/{id}.json` — full detail (drives the deputy page)

Keys/values are canonical English (`docs/glossario.md`); the site maps them to PT.

```json
{
  "id": 220714,
  "name": "Adail Filho",
  "photo_url": "https://www.camara.leg.br/internet/deputado/bandep/220714.jpg",
  "state": "AM",
  "current_party": "MDB",
  "current_condition": "titular",
  "current_status": "in_office",
  "in_office": true,
  "legislatures": [56, 57],
  "mandates": [{ "legislature": 57, "state": "AM" }],
  "parties": [
    { "party": "REPUBLICANOS", "start": "2023-02-01T00:00", "end": "2026-04-01T14:00", "legislature": 57 },
    { "party": "MDB",          "start": "2026-04-01T14:00", "end": null,               "legislature": 57 }
  ],
  "office_periods": [
    { "condition": "titular", "start": "2023-02-01T12:05", "end": null, "legislature": 57 }
  ],
  "names": [
    { "name": "Adail Filho", "start": "2023-02-01T00:00", "end": null }
  ]
}
```

### `deputados/index.json` — slim cards (directory + search)

```json
[
  { "id": 220714, "name": "Adail Filho", "party": "MDB", "state": "AM",
    "status": "in_office", "condition": "titular", "in_office": true,
    "legislatures": [56, 57] }
]
```

Sorted by `name` (objective ordering, per the no-editorial-bias rule). Small enough
to load once; the frontend filters client-side.

## Derived "current" fields — the rules

| Field | Rule |
|---|---|
| `current_status` | Read straight from `deputy.current_status` (transform set it from the latest settled `situação`): `in_office` / `substitute` / `on_leave` / `suspended` / `vacated` / `term_ended` / `null`. |
| `in_office` | `current_status == "in_office"`. |
| `current_condition` | `condition` of the open `office_period`; else the latest one's; `null` if none. |
| `current_party` | `party` of the `party_affiliation` with `end_at IS NULL`; else the latest by `start_at`; `null` if none. |
| `state` | from the latest `mandate` (current term). |
| `legislatures` | distinct `mandate.legislature`, ascending. |

These map directly to the directory's **"Em exercício" toggle** (default-on, latest
legislatura → ≈513) and the card status badges (`em exercício` / `suplente` /
`licenciado`).

## Build logic

1. Open the DB read-only.
2. For each `deputado`: query its `mandato`, `party_membership`, `exercicio`,
   `name_history`; derive the current fields above; assemble the timelines; write
   `deputados/{id}.json` (atomic).
3. Collect a slim card per deputy; write the `nome`-sorted `deputados/index.json`.
4. Print counts (detail files written, index size, deputies with `status_atual = null`).

## Testing (TDD)

Build a small fixture DB (the build's only contract is the schema) covering every
derivation branch, then assert the emitted JSON:

- **Migrator** (Adail-like) — two `partidos` entries, `partido_atual` = the open one.
- **Suplente cycles** (Garcês-like) — multiple `exercicio` rows; `status_atual` =
  `suplente` when the last interval is closed, `em_exercicio` when open.
- **Licenciado titular** — Titular with the current interval closed → `licenciado`.
- **No history** (one of the un-fetched) — present in output with `status_atual` and
  `partido_atual` = `null`, still carrying identity + `mandatos`.
- **Index** — sorted by `nome`; card fields correct; the em-exercício subset count.

No live calls; no `etl` imports — tests construct the fixture DB with SQL.

## Decisions (recorded in `docs/decisions.md`)

- **B1** — `build` is top-level `/build`, reads the DB via SQL (schema = the contract); no `etl` imports.
- **B2** — output to `build/output/` (gitignored); `/site` deploy wiring deferred.
- **B3** — detail file = full canonical entity + derived current fields; index = slim cards, `nome`-sorted.
- **B4** — directory default = latest legislatura + `em_exercicio` (≈513), as a default-on toggle; status badges `em exercício` / `suplente` / `licenciado`.

## Deferrals

- Future deputy-page sections (attendance, expenses, votes, bills, amendments,
  corporate influence) — added to `{id}.json` as their data sources are built.
- `/site` frontend + deploy wiring (where `build/output/` is served from).
- Party / proposition build outputs — their own specs.
