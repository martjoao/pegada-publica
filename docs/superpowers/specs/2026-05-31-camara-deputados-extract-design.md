# Câmara Deputados Extract — Design

**Date:** 2026-05-31
**Status:** Approved
**Stage:** ETL (Stage 1) — Extract

## Goal

Create the first ETL fetch script and the folder structure it lives in. The script fetches
the full roster of deputies (deputados) from the Câmara dos Deputados open-data API for both
in-scope legislaturas (56ª and 57ª) and saves the raw responses to disk.

This is a pure **Extract** step: fetch from the API, save raw responses. Parsing/loading into a
local DB is a separate later step. It also establishes the conventions (folder layout, shared
HTTP client, provenance wrapper, testing approach) for every future ETL source.

## Decisions

- **ETL output:** raw JSON landing files on disk. DB load comes later as its own script.
- **Scope:** Câmara deputies only (Senado is a sibling script added later).
- **Legislaturas:** both 56ª and 57ª (`idLegislatura=56` and `57`), one file each.
- **Tooling:** pip + `requirements.txt`, manual venv. Dependency: `requests`. Dev: `responses`.
- **Structure:** shared HTTP client + thin per-source module (approach B).

## Folder Structure

```
etl/
├── README.md                  # how to set up venv + run
├── requirements.txt           # requests
├── requirements-dev.txt       # responses, pytest
├── .gitignore                 # ignores data/ (fetched output isn't committed)
├── pegada_etl/
│   ├── __init__.py
│   ├── paths.py               # resolves data/raw/... locations
│   ├── http_client.py         # CamaraClient: GET w/ retry/backoff + auto-pagination
│   └── sources/
│       ├── __init__.py
│       └── camara/
│           ├── __init__.py
│           └── deputados.py    # the extract: fetch both legislaturas → raw files
├── tests/
│   ├── __init__.py
│   ├── test_http_client.py
│   └── test_deputados.py
└── data/                      # gitignored landing zone
    └── raw/camara/deputados/
        ├── legislatura-56.json
        └── legislatura-57.json
```

Run with: `python -m pegada_etl.sources.camara.deputados`

## Components

### `http_client.py` — `CamaraClient`
Wraps a `requests.Session`.
- Base URL `https://dadosabertos.camara.leg.br/api/v2`.
- Sets `Accept: application/json` and a descriptive `User-Agent` (API etiquette).
- `get_all(path, params)`: follows the API's `links` rel=`next` to collect every page's `dados`
  array, returning the merged list. Retries transient errors (5xx, timeouts, connection drops)
  with exponential backoff. Small politeness delay between page requests.

### `sources/camara/deputados.py`
- For each legislatura in `[56, 57]`, calls
  `client.get_all("/deputados", {"idLegislatura": n, "itens": 100, "ordem": "ASC", "ordenarPor": "nome"})`.
- Writes one file per legislatura via the provenance wrapper.

### `paths.py`
Single source of truth for the `data/raw/...` layout. Resolves absolute paths so the script
works regardless of the current working directory.

## Output File Format

Provenance-wrapped (matters for a transparency project). The `dados` records are untouched/raw;
only the `_meta` wrapper is added.

```json
{
  "_meta": {
    "source": "camara-dados-abertos",
    "endpoint": "/deputados",
    "legislatura": 57,
    "fetched_at": "2026-05-31T14:00:00Z",
    "record_count": 513
  },
  "dados": [ /* deputy records, exactly as returned by the API */ ]
}
```

## Error Handling

- Retry transient errors (5xx, timeouts, connection drops) with exponential backoff.
- Fail loudly on persistent errors (4xx, repeated failures) — do not write a partial file.
- Write to a temp file and atomically rename on success, so a crash never leaves a
  half-written `legislatura-57.json`.

## Testing (TDD)

Unit tests with a mocked HTTP layer (`responses` library), no live network calls:
- Pagination correctly follows `links`/`next` and merges pages across requests.
- Retry retries a transient failure then succeeds.
- Output file has the correct `_meta` (count, legislatura, endpoint) and the raw `dados`.

## Out of Scope (later steps)

- Senado Federal deputies/senators fetch.
- Parsing/transforming and loading into the local DB.
- Other Câmara endpoints (votes, expenses, bills).
