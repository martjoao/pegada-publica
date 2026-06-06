# Bio Extract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add extract-only bio crawlers for Câmara deputies (`extract/camara/bio.py`) and Senado senators (`extract/senado/bio.py`), landing one raw JSON file per entity.

**Architecture:** Two new per-house extract modules following the existing `historico.py` / `senado/detalhe.py` pattern — provenance-wrapped landing files, `skip_existing` resumability, per-entity error recovery. A `get()` method is added to `CamaraClient` (it only had `get_all()`); two path helpers are added to `common/paths.py`.

**Tech Stack:** Python 3, `requests`, `responses` (test mocking), `pytest`, SQLite (not touched here).

All commands run from `etl/` using the project venv: `cd etl && ...`

---

## File Map

| File | Action | What it does |
|------|--------|-------------|
| `common/http_client.py` | Modify | Add `CamaraClient.get()` for single-object endpoints |
| `common/paths.py` | Modify | Add `camara_bio_path()` and `senado_bio_path()` |
| `extract/camara/bio.py` | Create | Per-deputy `GET /deputados/{id}` crawl |
| `extract/senado/bio.py` | Create | Per-senator `GET /senador/{codigo}` crawl |
| `tests/test_http_client.py` | Modify | Tests for `CamaraClient.get()` |
| `tests/test_paths.py` | Modify | Tests for the two new path helpers |
| `tests/test_camara_bio_extract.py` | Create | Tests for `extract/camara/bio.py` |
| `tests/test_senado_bio_extract.py` | Create | Tests for `extract/senado/bio.py` |

---

## Task 1: Add `CamaraClient.get()`

**Files:**
- Modify: `common/http_client.py`
- Modify: `tests/test_http_client.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_http_client.py`:

```python
@responses.activate
def test_get_returns_parsed_json(client):
    responses.add(responses.GET, f"{BASE}/deputados/123",
                  json={"dados": {"id": 123, "nome": "Test"}}, status=200)

    result = client.get("/deputados/123")

    assert result == {"dados": {"id": 123, "nome": "Test"}}
    assert len(responses.calls) == 1


@responses.activate
def test_get_retries_transient_error_then_succeeds(client):
    responses.add(responses.GET, f"{BASE}/deputados/123", status=503)
    responses.add(responses.GET, f"{BASE}/deputados/123",
                  json={"dados": {"id": 123}}, status=200)

    result = client.get("/deputados/123")

    assert result["dados"]["id"] == 123
    assert len(responses.calls) == 2
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd etl && .venv/bin/python -m pytest tests/test_http_client.py::test_get_returns_parsed_json tests/test_http_client.py::test_get_retries_transient_error_then_succeeds -v
```

Expected: `AttributeError: 'CamaraClient' object has no attribute 'get'`

- [ ] **Step 3: Implement `CamaraClient.get()`**

In `common/http_client.py`, add after `get_all()`:

```python
def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """GET a single endpoint, returning the full JSON response dict (non-paginated)."""
    return self._get(self.base_url + path, params=params)
```

- [ ] **Step 4: Run tests to confirm passing**

```bash
cd etl && .venv/bin/python -m pytest tests/test_http_client.py -v
```

Expected: all pass (including the two new tests).

- [ ] **Step 5: Commit**

```bash
git add etl/common/http_client.py etl/tests/test_http_client.py
git commit -m "feat(etl): add CamaraClient.get() for single-object endpoints"
```

---

## Task 2: Add path helpers

**Files:**
- Modify: `common/paths.py`
- Modify: `tests/test_paths.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_paths.py`:

```python
def test_camara_bio_path_uses_deputy_id_filename():
    p = paths.camara_bio_path(226708, base=Path("/tmp/raw"))
    assert p == Path("/tmp/raw/camara/bio/226708.json")


def test_camara_bio_path_defaults_under_data_raw():
    p = paths.camara_bio_path(226708)
    assert p.parts[-4:] == ("raw", "camara", "bio", "226708.json")


def test_senado_bio_path_uses_codigo_filename():
    p = paths.senado_bio_path(5672, base=Path("/tmp/raw"))
    assert p == Path("/tmp/raw/senado/bio/5672.json")


def test_senado_bio_path_defaults_under_data_raw():
    p = paths.senado_bio_path(5672)
    assert p.parts[-4:] == ("raw", "senado", "bio", "5672.json")
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd etl && .venv/bin/python -m pytest tests/test_paths.py::test_camara_bio_path_uses_deputy_id_filename tests/test_paths.py::test_senado_bio_path_uses_codigo_filename -v
```

Expected: `AttributeError: module 'common.paths' has no attribute 'camara_bio_path'`

- [ ] **Step 3: Implement the helpers**

Append to `common/paths.py`:

```python
def camara_bio_path(deputy_id: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for one deputy's bio detail."""
    base = base if base is not None else DATA_RAW
    return base / "camara" / "bio" / f"{deputy_id}.json"


def senado_bio_path(codigo: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for one senator's bio detail."""
    base = base if base is not None else DATA_RAW
    return base / "senado" / "bio" / f"{codigo}.json"
```

- [ ] **Step 4: Run tests to confirm passing**

```bash
cd etl && .venv/bin/python -m pytest tests/test_paths.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add etl/common/paths.py etl/tests/test_paths.py
git commit -m "feat(etl): add camara_bio_path and senado_bio_path helpers"
```

---

## Task 3: `extract/camara/bio.py`

**Files:**
- Create: `extract/camara/bio.py`
- Create: `tests/test_camara_bio_extract.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_camara_bio_extract.py`:

```python
import json

import responses

from common import paths
from common.http_client import CamaraClient
from common.jsonio import write_json_atomic
from extract.camara import bio

BASE = "https://dadosabertos.camara.leg.br/api/v2"


def test_build_payload_wraps_with_meta():
    data = {"id": 226708, "nome": "Test Deputy", "nomeCivil": "Test Name"}
    payload = bio.build_payload(226708, data, fetched_at="2026-06-06T12:00:00Z")

    assert payload["dados"] == data
    meta = payload["_meta"]
    assert meta["source"] == "camara-dados-abertos"
    assert meta["endpoint"] == "/deputados/226708"
    assert meta["deputy_id"] == 226708
    assert meta["fetched_at"] == "2026-06-06T12:00:00Z"


@responses.activate
def test_run_writes_one_file_per_deputy(tmp_path):
    for dep_id in (10, 20):
        responses.add(
            responses.GET,
            f"{BASE}/deputados/{dep_id}",
            json={"dados": {"id": dep_id, "nome": f"Deputy {dep_id}"}, "links": []},
            status=200,
        )

    client = CamaraClient(backoff_base=0, page_delay=0)
    written = bio.run(client=client, deputy_ids=[10, 20], out_dir=tmp_path, delay=0)

    assert len(written) == 2
    f10 = json.loads((tmp_path / "camara" / "bio" / "10.json").read_text())
    assert f10["_meta"]["deputy_id"] == 10
    assert f10["_meta"]["endpoint"] == "/deputados/10"
    assert f10["dados"]["id"] == 10
    assert f10["dados"]["nome"] == "Deputy 10"


def test_run_skips_already_written_deputies(tmp_path):
    existing = paths.camara_bio_path(10, base=tmp_path)
    write_json_atomic({"_meta": {"deputy_id": 10}, "dados": "SENTINEL"}, existing)

    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, f"{BASE}/deputados/20",
                 json={"dados": {"id": 20}, "links": []}, status=200)
        client = CamaraClient(backoff_base=0, page_delay=0)
        written = bio.run(client=client, deputy_ids=[10, 20],
                          out_dir=tmp_path, delay=0, skip_existing=True)

    assert written == [paths.camara_bio_path(20, base=tmp_path)]
    assert json.loads(existing.read_text())["dados"] == "SENTINEL"


@responses.activate
def test_run_tolerates_individual_failures(tmp_path):
    responses.add(responses.GET, f"{BASE}/deputados/10", json={}, status=500)
    responses.add(responses.GET, f"{BASE}/deputados/20",
                  json={"dados": {"id": 20}, "links": []}, status=200)

    client = CamaraClient(backoff_base=0, page_delay=0)
    written = bio.run(client=client, deputy_ids=[10, 20], out_dir=tmp_path, delay=0)

    assert written == [paths.camara_bio_path(20, base=tmp_path)]
    assert not (tmp_path / "camara" / "bio" / "10.json").exists()
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd etl && .venv/bin/python -m pytest tests/test_camara_bio_extract.py -v
```

Expected: `ModuleNotFoundError: No module named 'extract.camara.bio'`

- [ ] **Step 3: Implement `extract/camara/bio.py`**

Create `extract/camara/bio.py`:

```python
"""Extract step: fetch each deputy's bio detail into raw landing files.

For every deputy in the roster this fetches GET /deputados/{id} and writes one
provenance-wrapped landing file under ``data/raw/camara/bio/``.

The deputy ids come from the roster landing files produced by
``extract.camara.deputados`` — you must run that first.

This is a pure extract: the ``dados`` field from the API response is saved
verbatim (raw PT). Resilient by design: ``skip_existing`` resumes where a
previous run stopped, and a failure on one deputy is logged and skipped.

Run with:

    python -m extract.camara.bio
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from common import paths
from common.http_client import CamaraClient
from common.jsonio import write_json_atomic
from extract.camara import historico

SOURCE = "camara-dados-abertos"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _endpoint(deputy_id: int) -> str:
    return f"/deputados/{deputy_id}"


def build_payload(
    deputy_id: int,
    data: Any,
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrap one deputy's raw bio data with provenance metadata."""
    return {
        "_meta": {
            "source": SOURCE,
            "endpoint": _endpoint(deputy_id),
            "deputy_id": deputy_id,
            "fetched_at": fetched_at or _utcnow_iso(),
        },
        "dados": data,
    }


def run(
    client: Optional[CamaraClient] = None,
    deputy_ids: Optional[Sequence[int]] = None,
    raw_base: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    delay: Optional[float] = None,
    skip_existing: bool = True,
) -> List[Path]:
    """Fetch bio detail for each deputy and write one raw landing file per deputy.

    ``deputy_ids`` defaults to every id in the roster landing files. ``delay``
    is the polite pause between deputies (defaults to the client's page delay).

    Returns the list of newly written file paths.
    """
    client = client or CamaraClient()
    if deputy_ids is None:
        deputy_ids = historico.deputy_ids_from_roster(raw_base=raw_base)
    if delay is None:
        delay = client.page_delay

    written: List[Path] = []
    skipped = 0
    failed: List[int] = []
    total = len(deputy_ids)
    for index, deputy_id in enumerate(deputy_ids):
        path = paths.camara_bio_path(deputy_id, base=out_dir)
        if skip_existing and path.exists():
            skipped += 1
            continue
        try:
            response = client.get(_endpoint(deputy_id))
            data = response.get("dados")
        except Exception as exc:
            failed.append(deputy_id)
            print(f"[{index + 1}/{total}] deputy {deputy_id}: FAILED — {exc}")
        else:
            write_json_atomic(build_payload(deputy_id, data), path)
            written.append(path)
            print(f"[{index + 1}/{total}] deputy {deputy_id} -> {path}")
        if delay and index + 1 < total:
            time.sleep(delay)

    print(f"done: {len(written)} written, {skipped} skipped, {len(failed)} failed")
    if failed:
        print(f"failed ids (re-run to retry): {failed}")
    return written


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run tests to confirm passing**

```bash
cd etl && .venv/bin/python -m pytest tests/test_camara_bio_extract.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add etl/extract/camara/bio.py etl/tests/test_camara_bio_extract.py
git commit -m "feat(etl): add extract/camara/bio.py for deputy bio detail crawl"
```

---

## Task 4: `extract/senado/bio.py`

**Files:**
- Create: `extract/senado/bio.py`
- Create: `tests/test_senado_bio_extract.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_senado_bio_extract.py`:

```python
import json

import responses

from common import paths
from common.http_client import SenadoClient
from common.jsonio import write_json_atomic
from extract.senado import bio, lista

BASE = "https://legis.senado.leg.br/dadosabertos"


def _bio_response(codigo):
    return {"DetalheParlamentar": {"Parlamentar": {"CodigoParlamentar": str(codigo)}}}


def test_build_payload_wraps_with_meta():
    data = _bio_response(5672)
    payload = bio.build_payload(5672, data, fetched_at="2026-06-06T12:00:00Z")

    assert payload["dados"] == data
    meta = payload["_meta"]
    assert meta["source"] == "senado-dados-abertos"
    assert meta["endpoint"] == "/senador/5672"
    assert meta["codigo"] == 5672
    assert meta["fetched_at"] == "2026-06-06T12:00:00Z"


@responses.activate
def test_run_writes_one_file_per_senator(tmp_path):
    for cod in (10, 20):
        responses.add(responses.GET, f"{BASE}/senador/{cod}",
                      json=_bio_response(cod), status=200)

    client = SenadoClient(backoff_base=0, page_delay=0)
    written = bio.run(client=client, codigos=[10, 20], out_dir=tmp_path, delay=0)

    assert len(written) == 2
    f10 = json.loads(paths.senado_bio_path(10, base=tmp_path).read_text())
    assert f10["_meta"]["codigo"] == 10
    assert f10["dados"]["DetalheParlamentar"]["Parlamentar"]["CodigoParlamentar"] == "10"


def test_run_skips_already_written(tmp_path):
    existing = paths.senado_bio_path(10, base=tmp_path)
    write_json_atomic({"_meta": {"codigo": 10}, "dados": "SENTINEL"}, existing)

    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, f"{BASE}/senador/20", json=_bio_response(20), status=200)
        client = SenadoClient(backoff_base=0, page_delay=0)
        written = bio.run(client=client, codigos=[10, 20],
                          out_dir=tmp_path, delay=0, skip_existing=True)

    assert written == [paths.senado_bio_path(20, base=tmp_path)]
    assert json.loads(existing.read_text())["dados"] == "SENTINEL"


@responses.activate
def test_run_tolerates_individual_failures(tmp_path):
    responses.add(responses.GET, f"{BASE}/senador/10", json={}, status=500)
    responses.add(responses.GET, f"{BASE}/senador/20", json=_bio_response(20), status=200)

    client = SenadoClient(backoff_base=0, page_delay=0)
    written = bio.run(client=client, codigos=[10, 20], out_dir=tmp_path, delay=0)

    assert written == [paths.senado_bio_path(20, base=tmp_path)]
    assert not paths.senado_bio_path(10, base=tmp_path).exists()


def test_codigos_default_to_roster(tmp_path):
    lista.save_payload(
        lista.build_payload(57, [
            {"IdentificacaoParlamentar": {"CodigoParlamentar": "7"}},
        ]),
        paths.senado_lista_path(57, base=tmp_path),
    )

    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, f"{BASE}/senador/7", json=_bio_response(7), status=200)
        client = SenadoClient(backoff_base=0, page_delay=0)
        written = bio.run(client=client, raw_base=tmp_path, out_dir=tmp_path, delay=0)

    assert paths.senado_bio_path(7, base=tmp_path) in written
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd etl && .venv/bin/python -m pytest tests/test_senado_bio_extract.py -v
```

Expected: `ModuleNotFoundError: No module named 'extract.senado.bio'`

- [ ] **Step 3: Implement `extract/senado/bio.py`**

Create `extract/senado/bio.py`:

```python
"""Extract step: fetch each senator's bio detail into raw landing files.

For every senator in the roster this fetches GET /senador/{codigo} and writes one
provenance-wrapped landing file under ``data/raw/senado/bio/``.

The senator codes come from the roster landing files produced by
``extract.senado.lista`` — you must run that first.

This is a pure extract: the API payload is saved verbatim (raw PT).
``skip_existing`` resumes where a previous run stopped; a failure on one senator
is logged and skipped, never aborting the whole crawl.

Run with:

    python -m extract.senado.bio
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from common import paths
from common.http_client import SenadoClient
from common.jsonio import write_json_atomic
from extract.senado import lista

SOURCE = "senado-dados-abertos"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _endpoint(codigo: int) -> str:
    return f"/senador/{codigo}"


def build_payload(
    codigo: int,
    data: Any,
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrap one senator's raw bio data with provenance metadata."""
    return {
        "_meta": {
            "source": SOURCE,
            "endpoint": _endpoint(codigo),
            "codigo": codigo,
            "fetched_at": fetched_at or _utcnow_iso(),
        },
        "dados": data,
    }


def run(
    client: Optional[SenadoClient] = None,
    codigos: Optional[Sequence[int]] = None,
    raw_base: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    delay: Optional[float] = None,
    skip_existing: bool = True,
) -> List[Path]:
    """Fetch bio detail for each senator and write one raw landing file per senator.

    ``codigos`` defaults to every code in the roster landing files. ``delay``
    is the polite pause between senators (defaults to the client's page delay).

    Returns the list of newly written file paths.
    """
    client = client or SenadoClient()
    if codigos is None:
        codigos = lista.senator_codes_from_roster(raw_base=raw_base)
    if delay is None:
        delay = client.page_delay

    written: List[Path] = []
    skipped = 0
    failed: List[int] = []
    total = len(codigos)
    for index, codigo in enumerate(codigos):
        path = paths.senado_bio_path(codigo, base=out_dir)
        if skip_existing and path.exists():
            skipped += 1
            continue
        try:
            data = client.get(_endpoint(codigo))
        except Exception as exc:
            failed.append(codigo)
            print(f"[{index + 1}/{total}] senator {codigo}: FAILED — {exc}")
        else:
            write_json_atomic(build_payload(codigo, data), path)
            written.append(path)
            print(f"[{index + 1}/{total}] senator {codigo} -> {path}")
        if delay and index + 1 < total:
            time.sleep(delay)

    print(f"done: {len(written)} written, {skipped} skipped, {len(failed)} failed")
    if failed:
        print(f"failed codes (re-run to retry): {failed}")
    return written


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run tests to confirm passing**

```bash
cd etl && .venv/bin/python -m pytest tests/test_senado_bio_extract.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
cd etl && .venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add etl/extract/senado/bio.py etl/tests/test_senado_bio_extract.py
git commit -m "feat(etl): add extract/senado/bio.py for senator bio detail crawl"
```

---

## Task 5: Run the extracts

Prerequisites: roster landing files must exist (`data/raw/camara/deputados/` and `data/raw/senado/lista/`).

- [ ] **Step 1: Run the Câmara bio crawl**

```bash
cd etl && .venv/bin/python -m extract.camara.bio
```

Expected: 924 lines like `[N/924] deputy {id} -> data/raw/camara/bio/{id}.json`, then `done: 924 written, 0 skipped, 0 failed`. Any failures are printed and safe to retry by re-running (skip_existing will skip the successes).

- [ ] **Step 2: Run the Senado bio crawl**

```bash
cd etl && .venv/bin/python -m extract.senado.bio
```

Expected: 318 lines like `[N/318] senator {codigo} -> data/raw/senado/bio/{codigo}.json`, then `done: 318 written, 0 skipped, 0 failed`.

- [ ] **Step 3: Spot-check the output**

```bash
cd etl && python3 -c "
import json
from pathlib import Path

# Deputy: pick first file and print bio fields
files = sorted(Path('data/raw/camara/bio').glob('*.json'))
print(f'Deputy files: {len(files)}')
d = json.loads(files[0].read_text())
print('Deputy meta:', d['_meta'])
print('Deputy bio keys:', list(d['dados'].keys()) if d['dados'] else 'None')

# Senator: pick first file
sfiles = sorted(Path('data/raw/senado/bio').glob('*.json'))
print(f'Senator files: {len(sfiles)}')
s = json.loads(sfiles[0].read_text())
print('Senator meta:', s['_meta'])
print('Senator bio keys:', list(s['dados'].keys()) if s['dados'] else 'None')
"
```

Expected: ~924 deputy files and ~318 senator files; bio keys include fields like `nomeCivil`, `dataNascimento`, `escolaridade` for deputies, and `DetalheParlamentar` structure for senators.

- [ ] **Step 4: Update decisions.md**

Open `docs/decisions.md` and append a new numbered decision at the bottom of the Decisions section (next number after 023):

```
**024 — Bio extract milestone: deputy and senator bio landing files crawled.**
`extract/camara/bio.py` (GET /deputados/{id}) and `extract/senado/bio.py`
(GET /senador/{codigo}) run end-to-end on live data. Raw bio files saved to
`data/raw/camara/bio/` and `data/raw/senado/bio/` (gitignored). The "Deputy
bio/detail fields" deferral in decisions.md is undeferred at the extract level;
transform/build wiring is a follow-on spec.
→ spec: `docs/superpowers/specs/2026-06-06-bio-extract-design.md`
```

(Fill in actual counts after the crawl completes.)

- [ ] **Step 5: Commit the context update**

```bash
git add docs/decisions.md
git commit -m "docs: record bio extract milestone (decision 024)"
```
