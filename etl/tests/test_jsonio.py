import json

from common.jsonio import write_json_atomic


def test_write_json_atomic_roundtrips_and_creates_parents(tmp_path):
    obj = {"_meta": {"x": 1}, "dados": [{"nome": "José"}]}
    out = tmp_path / "nested" / "deep" / "file.json"

    write_json_atomic(obj, out)

    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8")) == obj
    # unicode kept readable, not escaped
    assert "José" in out.read_text(encoding="utf-8")


def test_write_json_atomic_leaves_no_temp_file(tmp_path):
    out = tmp_path / "file.json"

    write_json_atomic({"a": 1}, out)

    assert [p.name for p in out.parent.iterdir()] == ["file.json"]


def test_write_json_atomic_overwrites_existing(tmp_path):
    out = tmp_path / "file.json"
    write_json_atomic({"v": 1}, out)
    write_json_atomic({"v": 2}, out)

    assert json.loads(out.read_text(encoding="utf-8")) == {"v": 2}
