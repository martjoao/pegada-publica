"""Extract step: fetch each deputy's full history into raw landing files.

The ``/deputados/{id}/historico`` endpoint takes no query parameters and returns
a deputy's complete cross-term history (party affiliation, in-office/exercise
status, and parliamentary-name changes) in a single unpaginated response. This
module fetches it for every deputy in the roster and writes one
provenance-wrapped JSON file per deputy under ``data/raw/camara/historico/``.

The deputy ids come from the roster landing files produced by
``extract.camara.deputados`` — you must run that first.

This is a pure extract: ``dados`` are saved exactly as the API returns them.

Run with:

    python -m extract.camara.historico
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from common import paths
from common.http_client import CamaraClient
from common.jsonio import write_json_atomic

SOURCE = "camara-dados-abertos"
LEGISLATURAS = (56, 57)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _endpoint(deputy_id: int) -> str:
    return f"/deputados/{deputy_id}/historico"


def build_payload(
    deputy_id: int,
    records: List[Dict[str, Any]],
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrap one deputy's raw history records with provenance metadata."""
    return {
        "_meta": {
            "source": SOURCE,
            "endpoint": _endpoint(deputy_id),
            "deputy_id": deputy_id,
            "fetched_at": fetched_at or _utcnow_iso(),
            "record_count": len(records),
        },
        "dados": records,
    }


def deputy_ids_from_roster(
    raw_base: Optional[Path] = None,
    legislaturas: Sequence[int] = LEGISLATURAS,
) -> List[int]:
    """Collect the unique deputy ids across the roster landing files, sorted."""
    ids = set()
    for legislatura in legislaturas:
        path = paths.camara_deputados_path(legislatura, base=raw_base)
        payload = json.loads(path.read_text(encoding="utf-8"))
        for record in payload.get("dados", []) or []:
            ids.add(record["id"])
    return sorted(ids)


def fetch_deputy(client: CamaraClient, deputy_id: int) -> List[Dict[str, Any]]:
    """Fetch one deputy's full history (no params, single unpaginated call)."""
    return client.get_all(_endpoint(deputy_id))


def run(
    client: Optional[CamaraClient] = None,
    deputy_ids: Optional[Sequence[int]] = None,
    raw_base: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    delay: Optional[float] = None,
    skip_existing: bool = True,
) -> List[Path]:
    """Fetch history for each deputy and write one raw landing file per deputy.

    ``deputy_ids`` defaults to every id in the roster landing files. ``delay``
    is the polite pause between deputies (defaults to the client's page delay).

    Resilient by design for a ~900-deputy crawl against a flaky public API:
    - ``skip_existing`` (default) skips deputies already on disk, so a re-run
      resumes where a previous run stopped instead of starting over.
    - a failure on one deputy (e.g. a 504 after retries) is logged and skipped,
      never aborting the whole crawl. Failed ids are re-attempted on the next run.

    Returns the list of newly written file paths.
    """
    client = client or CamaraClient()
    if deputy_ids is None:
        deputy_ids = deputy_ids_from_roster(raw_base=raw_base)
    if delay is None:
        delay = client.page_delay

    written: List[Path] = []
    skipped = 0
    failed: List[int] = []
    total = len(deputy_ids)
    for index, deputy_id in enumerate(deputy_ids):
        path = paths.camara_historico_path(deputy_id, base=out_dir)
        if skip_existing and path.exists():
            skipped += 1
            continue
        try:
            records = fetch_deputy(client, deputy_id)
        except Exception as exc:  # one bad deputy must not kill the crawl
            failed.append(deputy_id)
            print(f"[{index + 1}/{total}] deputy {deputy_id}: FAILED — {exc}")
        else:
            payload = build_payload(deputy_id, records)
            write_json_atomic(payload, path)
            written.append(path)
            print(f"[{index + 1}/{total}] deputy {deputy_id}: {len(records)} entries -> {path}")
        if delay and index + 1 < total:
            time.sleep(delay)

    print(f"done: {len(written)} written, {skipped} skipped, {len(failed)} failed")
    if failed:
        print(f"failed ids (re-run to retry): {failed}")
    return written


if __name__ == "__main__":
    run()
