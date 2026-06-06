"""Tests for extract.tse.receitas — receitas_candidatos download and manifest."""
import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from common import paths
from extract.tse.receitas import ELECTIONS, run


# ── helpers ──────────────────────────────────────────────────────────────────

COLUMNS = [
    "DS_ELEICAO", "DS_CARGO", "NM_CANDIDATO", "SG_PARTIDO",
    "NM_DOADOR", "NR_CPF_CNPJ_DOADOR", "VR_RECEITA", "DS_ORIGEM_RECEITA",
]

ROWS = [
    ["ELEIÇÕES GERAIS 2022", "DEPUTADO FEDERAL", "CAND A", "PT",
     "DOADOR A", "000", "500.00", "Recursos de pessoas físicas"],
    ["ELEIÇÕES GERAIS 2022", "GOVERNADOR", "CAND B", "MDB",
     "DOADOR B", "111", "200.00", "Recursos de pessoas físicas"],
]


def _make_zip(rows=ROWS, filename="receitas_candidatos_2022_BRASIL.csv"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf, delimiter=";")
        writer.writerow(COLUMNS)
        writer.writerows(rows)
        zf.writestr(filename, csv_buf.getvalue().encode("latin-1"))
    buf.seek(0)
    return buf.read()


class FakeDownloader:
    """Writes a pre-built ZIP to dest_path without making any HTTP request."""

    def __init__(self, zip_content: bytes):
        self._zip_content = zip_content

    def download(self, url: str, dest_path: Path) -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(self._zip_content)


# ── tests ────────────────────────────────────────────────────────────────────

def test_run_writes_zip_file(tmp_path):
    content = _make_zip()
    run(downloader=FakeDownloader(content), elections=(2022,), out_dir=tmp_path)
    assert paths.tse_receitas_zip_path(2022, base=tmp_path).read_bytes() == content


def test_run_writes_manifest_file(tmp_path):
    run(downloader=FakeDownloader(_make_zip()), elections=(2022,), out_dir=tmp_path)
    manifest_path = paths.tse_receitas_manifest_path(2022, base=tmp_path)
    assert manifest_path.exists()


def test_run_manifest_contains_correct_source(tmp_path):
    run(downloader=FakeDownloader(_make_zip()), elections=(2022,), out_dir=tmp_path)
    manifest = json.loads(
        paths.tse_receitas_manifest_path(2022, base=tmp_path).read_text()
    )
    assert manifest["_meta"]["source"] == "tse-dados-abertos"


def test_run_manifest_federal_rows_correct(tmp_path):
    # ROWS has 1 federal (DEPUTADO FEDERAL) and 1 non-federal (GOVERNADOR)
    run(downloader=FakeDownloader(_make_zip()), elections=(2022,), out_dir=tmp_path)
    manifest = json.loads(
        paths.tse_receitas_manifest_path(2022, base=tmp_path).read_text()
    )
    assert manifest["files"][0]["total_rows"] == 2
    assert manifest["files"][0]["federal_rows"] == 1


def test_run_processes_multiple_years(tmp_path):
    run(
        downloader=FakeDownloader(_make_zip()),
        elections=(2018, 2022),
        out_dir=tmp_path,
    )
    assert paths.tse_receitas_zip_path(2018, base=tmp_path).exists()
    assert paths.tse_receitas_zip_path(2022, base=tmp_path).exists()
    assert paths.tse_receitas_manifest_path(2018, base=tmp_path).exists()
    assert paths.tse_receitas_manifest_path(2022, base=tmp_path).exists()


def test_run_returns_written_paths(tmp_path):
    result = run(
        downloader=FakeDownloader(_make_zip()),
        elections=(2022,),
        out_dir=tmp_path,
    )
    assert result == [paths.tse_receitas_zip_path(2022, base=tmp_path)]


def test_elections_constant():
    assert ELECTIONS == (2018, 2022)
