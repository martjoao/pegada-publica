"""Tests for common.tse_zip — ZIP reading and manifest building."""
import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from common.tse_zip import ENCODING, FEDERAL_CARGOS, SOURCE, build_manifest


# ── helpers ──────────────────────────────────────────────────────────────────

COLUMNS = [
    "DS_ELEICAO", "DS_CARGO", "NM_CANDIDATO", "SG_PARTIDO",
    "NM_DOADOR", "NR_CPF_CNPJ_DOADOR", "VR_RECEITA", "DS_ORIGEM_RECEITA",
]

SAMPLE_ROWS = [
    # federal candidates
    ["ELEIÇÕES GERAIS 2022", "DEPUTADO FEDERAL", "JOAO SILVA", "PT",
     "MARIA SOUZA", "000.000.000-00", "1000.00", "Recursos de pessoas físicas"],
    ["ELEIÇÕES GERAIS 2022", "SENADOR", "ANA LIMA", "MDB",
     "CARLOS RAMOS", "111.111.111-11", "5000.00", "Recursos de pessoas físicas"],
    ["ELEIÇÕES GERAIS 2022", "PRESIDENTE", "JOSE BRASIL", "PL",
     "EMPRESA SA", "00.000.000/0001-00", "50000.00", "Recursos de partidos"],
    # non-federal — should NOT be counted in federal_rows
    ["ELEIÇÕES GERAIS 2022", "GOVERNADOR", "PEDRO ESTADUAL", "PP",
     "ANA SILVA", "222.222.222-22", "2000.00", "Recursos de pessoas físicas"],
]


def _make_zip(rows=SAMPLE_ROWS, filename="receitas_2022_BRASIL.csv", encoding=ENCODING):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf, delimiter=";")
        writer.writerow(COLUMNS)
        writer.writerows(rows)
        zf.writestr(filename, csv_buf.getvalue().encode(encoding))
    buf.seek(0)
    return buf.read()


def _write_zip(tmp_path: Path, content: bytes, name: str = "test.zip") -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


# ── constants ────────────────────────────────────────────────────────────────

def test_federal_cargos_contains_expected_values():
    assert "DEPUTADO FEDERAL" in FEDERAL_CARGOS
    assert "SENADOR" in FEDERAL_CARGOS
    assert "PRESIDENTE" in FEDERAL_CARGOS
    assert "GOVERNADOR" not in FEDERAL_CARGOS


def test_encoding_is_latin1():
    assert ENCODING == "latin-1"


def test_source_value():
    assert SOURCE == "tse-dados-abertos"


# ── build_manifest ───────────────────────────────────────────────────────────

def test_manifest_meta_fields(tmp_path):
    p = _write_zip(tmp_path, _make_zip())
    result = build_manifest(p, "http://example.com/2022.zip")
    assert result["_meta"]["source"] == "tse-dados-abertos"
    assert result["_meta"]["source_url"] == "http://example.com/2022.zip"
    assert result["_meta"]["encoding"] == "latin-1"
    assert "fetched_at" in result["_meta"]


def test_manifest_lists_csv_files(tmp_path):
    p = _write_zip(tmp_path, _make_zip(filename="receitas_2022_BRASIL.csv"))
    result = build_manifest(p, "http://example.com/2022.zip")
    assert len(result["files"]) == 1
    assert result["files"][0]["filename"] == "receitas_2022_BRASIL.csv"


def test_manifest_extracts_column_names(tmp_path):
    p = _write_zip(tmp_path, _make_zip())
    result = build_manifest(p, "http://example.com/2022.zip")
    assert result["files"][0]["columns"] == COLUMNS


def test_manifest_counts_total_rows(tmp_path):
    p = _write_zip(tmp_path, _make_zip())
    result = build_manifest(p, "http://example.com/2022.zip")
    assert result["files"][0]["total_rows"] == 4


def test_manifest_counts_only_federal_rows(tmp_path):
    # 3 federal (DEPUTADO FEDERAL, SENADOR, PRESIDENTE) + 1 non-federal (GOVERNADOR)
    p = _write_zip(tmp_path, _make_zip())
    result = build_manifest(p, "http://example.com/2022.zip")
    assert result["files"][0]["federal_rows"] == 3


def test_manifest_handles_multi_file_zip(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for state in ("SP", "RJ"):
            csv_buf = io.StringIO()
            writer = csv.writer(csv_buf, delimiter=";")
            writer.writerow(COLUMNS)
            # 1 federal row per state
            writer.writerow(
                ["ELEIÇÕES GERAIS 2022", "DEPUTADO FEDERAL", f"CAND {state}", "PT",
                 "DOADOR", "000", "100.00", "Recursos de pessoas físicas"]
            )
            zf.writestr(f"receitas_2022_{state}.csv", csv_buf.getvalue().encode(ENCODING))
    buf.seek(0)
    p = tmp_path / "multi.zip"
    p.write_bytes(buf.read())

    result = build_manifest(p, "http://example.com/multi.zip")
    assert len(result["files"]) == 2
    filenames = {f["filename"] for f in result["files"]}
    assert filenames == {"receitas_2022_SP.csv", "receitas_2022_RJ.csv"}
    for f in result["files"]:
        assert f["total_rows"] == 1
        assert f["federal_rows"] == 1


def test_manifest_raises_if_no_csv_in_zip(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.txt", "nothing here")
    buf.seek(0)
    p = tmp_path / "empty.zip"
    p.write_bytes(buf.read())
    with pytest.raises(ValueError, match="No CSV files found"):
        build_manifest(p, "http://example.com/empty.zip")


def test_manifest_raises_if_ds_cargo_column_missing(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf, delimiter=";")
        writer.writerow(["COL_A", "COL_B"])  # no DS_CARGO
        writer.writerow(["val", "val"])
        zf.writestr("bad.csv", csv_buf.getvalue().encode(ENCODING))
    buf.seek(0)
    p = tmp_path / "bad.zip"
    p.write_bytes(buf.read())
    with pytest.raises(ValueError, match="DS_CARGO"):
        build_manifest(p, "http://example.com/bad.zip")


def test_manifest_raises_on_corrupt_zip(tmp_path):
    p = tmp_path / "corrupt.zip"
    p.write_bytes(b"this is not a zip file")
    with pytest.raises(zipfile.BadZipFile, match="Corrupt or invalid ZIP"):
        build_manifest(p, "http://example.com/corrupt.zip")


def test_manifest_name_filter_excludes_non_matching_csvs(tmp_path):
    """ZIPs with mixed file types (e.g., receitas + despesas) are filtered by name."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # receitas file — has DS_CARGO, should be included
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf, delimiter=";")
        writer.writerow(COLUMNS)
        writer.writerow(SAMPLE_ROWS[0])  # DEPUTADO FEDERAL row
        zf.writestr("receitas_candidatos_2022_SP.csv", csv_buf.getvalue().encode(ENCODING))
        # despesas file — no DS_CARGO, should be excluded by filter
        csv_buf2 = io.StringIO()
        writer2 = csv.writer(csv_buf2, delimiter=";")
        writer2.writerow(["COL_A", "VR_PAGTO_DESPESA"])  # no DS_CARGO
        writer2.writerow(["x", "100.00"])
        zf.writestr("despesas_pagas_candidatos_2022_SP.csv", csv_buf2.getvalue().encode(ENCODING))
    buf.seek(0)
    p = tmp_path / "mixed.zip"
    p.write_bytes(buf.read())

    result = build_manifest(
        p, "http://example.com/mixed.zip",
        name_filter=lambda n: n.lower().startswith("receitas_candidatos_"),
    )
    assert len(result["files"]) == 1
    assert result["files"][0]["filename"] == "receitas_candidatos_2022_SP.csv"
    assert result["files"][0]["federal_rows"] == 1


def test_manifest_strips_bom_from_first_column(tmp_path):
    """Some TSE files open with a UTF-8 BOM despite being latin-1."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf, delimiter=";")
        # Write normal column names; we'll prepend the raw UTF-8 BOM bytes below
        writer.writerow(COLUMNS)
        writer.writerows(SAMPLE_ROWS[:1])
        # Prepend raw UTF-8 BOM bytes (\xef\xbb\xbf) to the latin-1 encoded content.
        # This simulates TSE files that carry a BOM marker even though they are latin-1.
        raw_bytes = b"\xef\xbb\xbf" + csv_buf.getvalue().encode(ENCODING)
        zf.writestr("bom.csv", raw_bytes)
    buf.seek(0)
    p = tmp_path / "bom.zip"
    p.write_bytes(buf.read())
    result = build_manifest(p, "http://example.com/bom.zip")
    assert result["files"][0]["columns"][0] == COLUMNS[0]  # BOM stripped
