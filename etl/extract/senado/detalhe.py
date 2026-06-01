"""Extract step: fetch each senator's mandates and party affiliations.

For every senator in the roster this fetches two per-senator resources and writes
one provenance-wrapped landing file each:

- ``/senador/{cod}/mandatos`` — mandates with dated ``Exercicio`` rows (the
  office-period source), under ``data/raw/senado/mandatos/``;
- ``/senador/{cod}/filiacoes`` — dated party affiliation history (the
  party-at-vote-time source), under ``data/raw/senado/filiacoes/``.

The senator codes come from the roster landing files produced by
``extract.senado.lista`` — you must run that first.

This is a pure extract: the API payloads are saved verbatim (raw PT, full
envelope). Resilient by design for a per-senator crawl against a public API:
``skip_existing`` resumes where a previous run stopped, and a failure on one
resource is logged and skipped, never aborting the whole crawl.

Run with:

    python -m extract.senado.detalhe
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

# resource name -> (endpoint suffix, path resolver)
_RESOURCES = {
    "mandatos": ("/mandatos", paths.senado_mandatos_path),
    "filiacoes": ("/filiacoes", paths.senado_filiacoes_path),
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _endpoint(resource: str, codigo: int) -> str:
    return f"/senador/{codigo}{_RESOURCES[resource][0]}"


def build_payload(
    resource: str,
    codigo: int,
    data: Any,
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrap one senator's raw resource payload with provenance metadata."""
    return {
        "_meta": {
            "source": SOURCE,
            "endpoint": _endpoint(resource, codigo),
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
    """Fetch mandatos + filiacoes for each senator, one landing file per resource.

    ``codigos`` defaults to every code in the roster landing files. ``delay`` is the
    polite pause between senators (defaults to the client's page delay).

    Returns the list of newly written file paths.
    """
    client = client or SenadoClient()
    if codigos is None:
        codigos = lista.senator_codes_from_roster(raw_base=raw_base)
    if delay is None:
        delay = client.page_delay

    written: List[Path] = []
    skipped = 0
    failed: List[str] = []
    total = len(codigos)
    for index, codigo in enumerate(codigos):
        for resource, (suffix, resolve) in _RESOURCES.items():
            path = resolve(codigo, base=out_dir)
            if skip_existing and path.exists():
                skipped += 1
                continue
            try:
                data = client.get(_endpoint(resource, codigo))
            except Exception as exc:  # one bad resource must not kill the crawl
                failed.append(f"{codigo}/{resource}")
                print(f"[{index + 1}/{total}] senator {codigo} {resource}: FAILED — {exc}")
            else:
                write_json_atomic(build_payload(resource, codigo, data), path)
                written.append(path)
                print(f"[{index + 1}/{total}] senator {codigo} {resource} -> {path}")
        if delay and index + 1 < total:
            time.sleep(delay)

    print(f"done: {len(written)} written, {skipped} skipped, {len(failed)} failed")
    if failed:
        print(f"failed (re-run to retry): {failed}")
    return written


if __name__ == "__main__":
    run()
