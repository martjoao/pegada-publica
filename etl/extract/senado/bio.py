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
