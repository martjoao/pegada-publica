from pathlib import Path

from common import paths


def test_camara_deputados_path_uses_legislatura_filename():
    p = paths.camara_deputados_path(57, base=Path("/tmp/raw"))
    assert p == Path("/tmp/raw/camara/deputados/legislatura-57.json")


def test_camara_deputados_path_defaults_under_data_raw():
    p = paths.camara_deputados_path(56)
    parts = p.parts
    assert parts[-4:] == ("raw", "camara", "deputados", "legislatura-56.json")


def test_camara_historico_path_uses_deputy_id_filename():
    p = paths.camara_historico_path(226708, base=Path("/tmp/raw"))
    assert p == Path("/tmp/raw/camara/historico/226708.json")


def test_camara_historico_path_defaults_under_data_raw():
    p = paths.camara_historico_path(74646)
    parts = p.parts
    assert parts[-4:] == ("raw", "camara", "historico", "74646.json")


def test_senado_lista_path_uses_legislatura_filename():
    p = paths.senado_lista_path(57, base=Path("/tmp/raw"))
    assert p == Path("/tmp/raw/senado/lista/legislatura-57.json")


def test_senado_lista_path_defaults_under_data_raw():
    p = paths.senado_lista_path(56)
    assert p.parts[-4:] == ("raw", "senado", "lista", "legislatura-56.json")


def test_senado_mandatos_path_uses_codigo_filename():
    p = paths.senado_mandatos_path(5672, base=Path("/tmp/raw"))
    assert p == Path("/tmp/raw/senado/mandatos/5672.json")


def test_senado_filiacoes_path_uses_codigo_filename():
    p = paths.senado_filiacoes_path(5672, base=Path("/tmp/raw"))
    assert p == Path("/tmp/raw/senado/filiacoes/5672.json")


def test_senado_detail_paths_default_under_data_raw():
    assert paths.senado_mandatos_path(5672).parts[-3:] == ("senado", "mandatos", "5672.json")
    assert paths.senado_filiacoes_path(5672).parts[-3:] == ("senado", "filiacoes", "5672.json")


def test_db_path_defaults_under_data():
    p = paths.db_path()
    parts = p.parts
    assert parts[-2:] == ("data", "pegada.db")


def test_db_path_accepts_base_override():
    p = paths.db_path(base=Path("/tmp/x"))
    assert p == Path("/tmp/x/pegada.db")
