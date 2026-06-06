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
