"""Extract step: fetch the Senado senator roster into raw landing files.

For each in-scope legislatura (56ª and 57ª) this fetches the full senator list
from the Senado open-data API and writes one provenance-wrapped JSON file per
legislatura under ``data/raw/senado/lista/``.

Each legislatura's list (``/senador/lista/legislatura/{n}``) returns everyone who
held a seat that term — titulares plus suplentes who took office (~245 entries).
Senate mandates are 8 years and span two legislatures, so the two files overlap;
the senator codes are deduplicated downstream.

This is a pure extract: the ``dados`` records are saved exactly as the API returns
them (raw PT). The ``CodigoParlamentar`` of each is the stable page URL key.

Run with:

    python -m extract.senado.lista
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from common import paths
from common.http_client import SenadoClient
from common.jsonio import write_json_atomic
from common.senado_json import as_list, unwrap

SOURCE = "senado-dados-abertos"
LEGISLATURAS = (56, 57)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _endpoint(legislatura: int) -> str:
    return f"/senador/lista/legislatura/{legislatura}"


def build_payload(
    legislatura: int,
    records: List[Dict[str, Any]],
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrap raw senator records with provenance metadata."""
    return {
        "_meta": {
            "source": SOURCE,
            "endpoint": _endpoint(legislatura),
            "legislatura": legislatura,
            "fetched_at": fetched_at or _utcnow_iso(),
            "record_count": len(records),
        },
        "dados": records,
    }


def save_payload(payload: Dict[str, Any], path: Path) -> None:
    """Write ``payload`` as pretty JSON, atomically (temp file + rename)."""
    write_json_atomic(payload, path)


def fetch_legislatura(client: SenadoClient, legislatura: int) -> List[Dict[str, Any]]:
    """Fetch the senator roster for a single legislatura (unwrapped to a list)."""
    payload = client.get(_endpoint(legislatura))
    node = unwrap(payload, "ListaParlamentarLegislatura", "Parlamentares", "Parlamentar")
    return as_list(node)


def senator_codes_from_roster(
    raw_base: Optional[Path] = None,
    legislaturas: Sequence[int] = LEGISLATURAS,
) -> List[int]:
    """Collect the unique senator codes across the roster landing files, sorted."""
    codes = set()
    for legislatura in legislaturas:
        path = paths.senado_lista_path(legislatura, base=raw_base)
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for record in payload.get("dados", []) or []:
            codes.add(int(record["IdentificacaoParlamentar"]["CodigoParlamentar"]))
    return sorted(codes)


def run(
    client: Optional[SenadoClient] = None,
    legislaturas: Sequence[int] = LEGISLATURAS,
    out_dir: Optional[Path] = None,
) -> List[Path]:
    """Fetch each legislatura and write one raw landing file per term.

    Returns the list of written file paths.
    """
    client = client or SenadoClient()
    written: List[Path] = []
    for legislatura in legislaturas:
        records = fetch_legislatura(client, legislatura)
        payload = build_payload(legislatura, records)
        path = paths.senado_lista_path(legislatura, base=out_dir)
        save_payload(payload, path)
        print(f"legislatura {legislatura}: {len(records)} senators -> {path}")
        written.append(path)
    return written


if __name__ == "__main__":
    run()
