"""Extract step: download TSE consulta_cand bulk ZIPs for 2018 and 2022.

Downloads the TSE candidate registry (including NR_CPF_CANDIDATO) from the TSE
open-data portal and saves verbatim to data/raw/tse/candidatos/.  A manifest
JSON is written alongside each ZIP.

These CPFs are used in the transform step to link TSE candidates to the
deputy/senator entities in pegada.db (requires the bio-detail extract to have
run first to populate CPFs on the Câmara/Senado side).

IMPORTANT: Verify CANDIDATOS_URLS against https://dadosabertos.tse.jus.br before
running.  The portal pages to check are:
  2022: https://dadosabertos.tse.jus.br/dataset/candidatos-2022
  2018: https://dadosabertos.tse.jus.br/dataset/candidatos-2018

Run with:
    python -m extract.tse.candidatos
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence

from common import paths
from common.http_client import TseDownloader
from common.jsonio import write_json_atomic
from common.tse_zip import build_manifest

ELECTIONS = (2018, 2022)

# VERIFY these URLs against the TSE open-data portal before running.
CANDIDATOS_URLS: Dict[int, str] = {
    2018: "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2018.zip",
    2022: "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2022.zip",
}


def run(
    downloader: Optional[TseDownloader] = None,
    elections: Sequence[int] = ELECTIONS,
    out_dir: Optional[Path] = None,
) -> List[Path]:
    """Download each election year's consulta_cand ZIP and write a manifest.

    Returns the list of written ZIP paths.
    """
    downloader = downloader or TseDownloader()
    written: List[Path] = []

    for year in elections:
        url = CANDIDATOS_URLS[year]
        zip_path = paths.tse_candidatos_zip_path(year, base=out_dir)
        manifest_path = paths.tse_candidatos_manifest_path(year, base=out_dir)

        print(f"candidatos {year}: downloading from {url} ...")
        downloader.download(url, zip_path)
        print(f"  saved {zip_path} ({zip_path.stat().st_size:,} bytes)")

        manifest = build_manifest(zip_path, url)
        write_json_atomic(manifest, manifest_path)

        for f in manifest["files"]:
            print(
                f"  {f['filename']}: {f['total_rows']:,} rows, "
                f"{f['federal_rows']:,} federal"
            )

        written.append(zip_path)

    return written


if __name__ == "__main__":
    run()
