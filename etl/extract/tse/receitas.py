"""Extract step: download TSE receitas_candidatos bulk ZIPs for 2018 and 2022.

Downloads campaign donation CSVs from the TSE open-data portal and saves them
verbatim to data/raw/tse/receitas/.  A manifest JSON is written alongside each
ZIP, recording column names and row counts — resolving the open verification
item in decisions.md about TSE column names.

IMPORTANT: Verify RECEITAS_URLS against https://dadosabertos.tse.jus.br before
running.  The portal pages to check are:
  2022: https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2022
  2018: https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2018

Run with:
    python -m extract.tse.receitas
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from common import paths
from common.http_client import TseDownloader
from common.jsonio import write_json_atomic
from common.tse_zip import build_manifest

ELECTIONS = (2018, 2022)

RECEITAS_URLS: Dict[int, str] = {
    2018: "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2018.zip",
    2022: "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2022.zip",
}


def run(
    downloader: Optional[TseDownloader] = None,
    elections: Sequence[int] = ELECTIONS,
    out_dir: Optional[Path] = None,
) -> List[Path]:
    """Download each election year's receitas ZIP and write a manifest alongside it.

    Returns the list of written ZIP paths.
    """
    downloader = downloader or TseDownloader()
    written: List[Path] = []

    for year in elections:
        url = RECEITAS_URLS[year]
        zip_path = paths.tse_receitas_zip_path(year, base=out_dir)
        manifest_path = paths.tse_receitas_manifest_path(year, base=out_dir)

        print(f"receitas {year}: downloading from {url} ...")
        downloader.download(url, zip_path)
        print(f"  saved {zip_path} ({zip_path.stat().st_size:,} bytes)")

        manifest = build_manifest(
            zip_path, url,
            # Select only receitas_candidatos_YEAR_STATE.csv files.
            # Excludes receitas_candidatos_doador_originario_* (no DS_CARGO).
            name_filter=lambda n: bool(
                re.match(r"receitas_candidatos_\d{4}_", n.lower())
            ),
        )
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
