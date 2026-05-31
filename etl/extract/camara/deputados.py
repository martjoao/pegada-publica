"""Extract step: fetch the Câmara dos Deputados roster into raw landing files.

For each in-scope legislatura (56ª and 57ª) this fetches the full deputy list
from the Câmara open-data API and writes one provenance-wrapped JSON file per
legislatura under ``data/raw/camara/deputados/``.

This is a pure extract: the ``dados`` records are saved exactly as the API
returns them. Parsing/loading into the local DB is a separate later step.

Run with:

    python -m extract.camara.deputados
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from common import paths
from common.http_client import CamaraClient

ENDPOINT = "/deputados"
SOURCE = "camara-dados-abertos"
LEGISLATURAS = (56, 57)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_payload(
    legislatura: int,
    records: List[Dict[str, Any]],
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrap raw deputy records with provenance metadata."""
    return {
        "_meta": {
            "source": SOURCE,
            "endpoint": ENDPOINT,
            "legislatura": legislatura,
            "fetched_at": fetched_at or _utcnow_iso(),
            "record_count": len(records),
        },
        "dados": records,
    }


def save_payload(payload: Dict[str, Any], path: Path) -> None:
    """Write ``payload`` as pretty JSON, atomically (temp file + rename).

    Writing to a temp file in the same directory and renaming on success means
    a crash mid-write never leaves a half-written landing file behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def fetch_legislatura(client: CamaraClient, legislatura: int) -> List[Dict[str, Any]]:
    """Fetch the full deputy roster for a single legislatura."""
    return client.get_all(
        ENDPOINT,
        {
            "idLegislatura": legislatura,
            "itens": 100,
            "ordem": "ASC",
            "ordenarPor": "nome",
        },
    )


def run(
    client: Optional[CamaraClient] = None,
    legislaturas: Sequence[int] = LEGISLATURAS,
    out_dir: Optional[Path] = None,
) -> List[Path]:
    """Fetch each legislatura and write one raw landing file per term.

    Returns the list of written file paths.
    """
    client = client or CamaraClient()
    written: List[Path] = []
    for legislatura in legislaturas:
        records = fetch_legislatura(client, legislatura)
        payload = build_payload(legislatura, records)
        path = paths.camara_deputados_path(legislatura, base=out_dir)
        save_payload(payload, path)
        print(
            f"legislatura {legislatura}: {len(records)} deputies -> {path}"
        )
        written.append(path)
    return written


if __name__ == "__main__":
    run()
