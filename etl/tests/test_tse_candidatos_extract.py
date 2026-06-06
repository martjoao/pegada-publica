"""Tests for extract.tse.candidatos — consulta_cand download and manifest."""
import csv
import io
import json
import zipfile
from pathlib import Path

from common import paths
from extract.tse.candidatos import ELECTIONS, run


# ── helpers ──────────────────────────────────────────────────────────────────

COLUMNS = [
    "DS_ELEICAO", "DS_CARGO", "NM_CANDIDATO", "SG_PARTIDO",
    "NR_CPF_CANDIDATO", "SG_UF", "NR_CANDIDATO",
]

ROWS = [
    ["ELEIÇÕES GERAIS 2022", "DEPUTADO FEDERAL", "CAND A", "PT",
     "000.000.000-00", "SP", "1234"],
    ["ELEIÇÕES GERAIS 2022", "GOVERNADOR", "CAND B", "MDB",
     "111.111.111-11", "RJ", "5678"],
]


def _make_zip(rows=ROWS, filename="consulta_cand_2022_BRASIL.csv"):
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
    def __init__(self, zip_content: bytes):
        self._zip_content = zip_content

    def download(self, url: str, dest_path: Path) -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(self._zip_content)


# ── tests ────────────────────────────────────────────────────────────────────

def test_run_writes_zip_file(tmp_path):
    content = _make_zip()
    run(downloader=FakeDownloader(content), elections=(2022,), out_dir=tmp_path)
    assert paths.tse_candidatos_zip_path(2022, base=tmp_path).read_bytes() == content


def test_run_writes_manifest_file(tmp_path):
    run(downloader=FakeDownloader(_make_zip()), elections=(2022,), out_dir=tmp_path)
    assert paths.tse_candidatos_manifest_path(2022, base=tmp_path).exists()


def test_run_manifest_federal_rows_correct(tmp_path):
    # ROWS has 1 federal (DEPUTADO FEDERAL) and 1 non-federal (GOVERNADOR)
    run(downloader=FakeDownloader(_make_zip()), elections=(2022,), out_dir=tmp_path)
    manifest = json.loads(
        paths.tse_candidatos_manifest_path(2022, base=tmp_path).read_text()
    )
    assert manifest["files"][0]["total_rows"] == 2
    assert manifest["files"][0]["federal_rows"] == 1


def test_run_processes_multiple_years(tmp_path):
    run(
        downloader=FakeDownloader(_make_zip()),
        elections=(2018, 2022),
        out_dir=tmp_path,
    )
    assert paths.tse_candidatos_zip_path(2018, base=tmp_path).exists()
    assert paths.tse_candidatos_zip_path(2022, base=tmp_path).exists()
    assert paths.tse_candidatos_manifest_path(2018, base=tmp_path).exists()
    assert paths.tse_candidatos_manifest_path(2022, base=tmp_path).exists()


def test_run_returns_written_paths(tmp_path):
    result = run(
        downloader=FakeDownloader(_make_zip()),
        elections=(2022,),
        out_dir=tmp_path,
    )
    assert result == [paths.tse_candidatos_zip_path(2022, base=tmp_path)]


def test_elections_constant():
    assert ELECTIONS == (2018, 2022)
