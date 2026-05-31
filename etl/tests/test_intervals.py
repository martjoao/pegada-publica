"""Interval-builder tests, using the real historico transitions captured during
design (Allan Garcês 226708, Adail Filho 220714, a titular ministerial leave)."""
from transform import intervals


def _entry(dataHora, partido, nome, cond, sit, desc, leg=57):
    return {
        "dataHora": dataHora,
        "siglaPartido": partido,
        "nome": nome,
        "condicaoEleitoral": cond,
        "situacao": sit,
        "descricaoStatus": desc,
        "idLegislatura": leg,
    }


# --- Allan Garcês (suplente): real subset of his 57ª history ---------------
# Real direction (confirmed live): "Dr. Allan Garcês" until 2024-07-18, then "Allan Garcês".
GARCES = [
    _entry("2023-02-01T00:00", "PP", "Dr. Allan Garcês", None, None,
           "Partido no início da legislatura / Nome no início da legislatura"),
    _entry("2023-09-13T14:53", "PP", "Dr. Allan Garcês", "Suplente", "Convocado",
           "Diverso - Convocação Eleito ou Suplente - Aguardando Convocação"),
    _entry("2023-09-13T16:01", "PP", "Dr. Allan Garcês", "Suplente", "Exercício",
           "Entrada - Posse de Suplente - Posse como Suplente"),
    _entry("2024-07-18T15:26", "PP", "Allan Garcês", "Suplente", "Exercício",
           "Alteração de nome parlamentar"),
    _entry("2024-12-03T10:11", "PP", "Allan Garcês", "Suplente", "Suplência",
           "Saída - Afastamento sem prazo determinado - Afastamento de Suplente (automático)"),
    _entry("2024-12-06T17:43", "PP", "Allan Garcês", "Suplente", "Exercício",
           "Entrada - Reassunção"),
    _entry("2025-02-01T08:38", "PP", "Allan Garcês", "Suplente", "Suplência",
           "Saída - Afastamento sem prazo determinado - Afastamento de Suplente (automático)"),
]


def test_exercise_intervals_suplente_ignores_convocado_and_name_change():
    got = intervals.exercise_intervals(GARCES)
    assert got == [
        {"legislatura": 57, "condicao": "Suplente",
         "start_at": "2023-09-13T16:01", "end_at": "2024-12-03T10:11"},
        {"legislatura": 57, "condicao": "Suplente",
         "start_at": "2024-12-06T17:43", "end_at": "2025-02-01T08:38"},
    ]


def test_name_intervals_tracks_parliamentary_name_change():
    got = intervals.name_intervals(GARCES)
    assert got == [
        {"nome": "Dr. Allan Garcês", "start_at": "2023-02-01T00:00", "end_at": "2024-07-18T15:26"},
        {"nome": "Allan Garcês", "start_at": "2024-07-18T15:26", "end_at": None},
    ]


def test_party_intervals_single_party_whole_term():
    got = intervals.party_intervals(GARCES)
    assert got == [
        {"legislatura": 57, "sigla_partido": "PP",
         "start_at": "2023-02-01T00:00", "end_at": None,
         "descricao_origem": "Partido no início da legislatura / Nome no início da legislatura"},
    ]


# --- Adail Filho (party migration REPUBLICANOS -> MDB) ---------------------
ADAIL = [
    _entry("2023-02-01T00:00", "REPUBLICANOS", "Adail Filho", None, None,
           "Partido no início da legislatura / Nome no início da legislatura"),
    _entry("2023-02-01T12:05", "REPUBLICANOS", "Adail Filho", "Titular", "Exercício",
           "Entrada - Posse de Eleito Titular - Posse na Sessão Preparatória"),
    _entry("2026-04-01T14:00", "MDB", "Adail Filho", "Titular", "Exercício",
           "Alteração de partido"),
]


def test_party_intervals_captures_dated_migration():
    got = intervals.party_intervals(ADAIL)
    assert got == [
        {"legislatura": 57, "sigla_partido": "REPUBLICANOS",
         "start_at": "2023-02-01T00:00", "end_at": "2026-04-01T14:00",
         "descricao_origem": "Partido no início da legislatura / Nome no início da legislatura"},
        {"legislatura": 57, "sigla_partido": "MDB",
         "start_at": "2026-04-01T14:00", "end_at": None,
         "descricao_origem": "Alteração de partido"},
    ]


# --- Cross-term: same party in 56 and 57 -> two per-term intervals ----------
CROSS_TERM = [
    _entry("2019-02-01T00:00", "PSDB", "Fulano", None, None,
           "Partido no início da legislatura / Nome no início da legislatura", leg=56),
    _entry("2023-01-31T23:59", "PSDB", "Fulano", "Titular", "Fim de Mandato",
           "Saída - Afastamento definitivo - Término da Legislatura", leg=56),
    _entry("2023-02-01T00:00", "PSDB", "Fulano", None, None,
           "Partido no início da legislatura / Nome no início da legislatura", leg=57),
]


def test_party_intervals_split_at_legislatura_boundary():
    got = intervals.party_intervals(CROSS_TERM)
    assert got == [
        {"legislatura": 56, "sigla_partido": "PSDB",
         "start_at": "2019-02-01T00:00", "end_at": "2023-02-01T00:00",
         "descricao_origem": "Partido no início da legislatura / Nome no início da legislatura"},
        {"legislatura": 57, "sigla_partido": "PSDB",
         "start_at": "2023-02-01T00:00", "end_at": None,
         "descricao_origem": "Partido no início da legislatura / Nome no início da legislatura"},
    ]


# --- Titular ministerial leave: Licença closes the interval, last stays open -
TITULAR_LEAVE = [
    _entry("2023-02-01T12:05", "PP", "Fulano", "Titular", "Exercício",
           "Entrada - Posse de Eleito Titular - Posse na Sessão Preparatória"),
    _entry("2023-09-13T14:53", "PP", "Fulano", "Titular", "Licença",
           "Saída - Afastamento sem prazo determinado - Ministro de Estado"),
    _entry("2024-12-03T10:11", "PP", "Fulano", "Titular", "Exercício",
           "Entrada - Reassunção"),
]


def test_exercise_intervals_titular_leave_and_open_tail():
    got = intervals.exercise_intervals(TITULAR_LEAVE)
    assert got == [
        {"legislatura": 57, "condicao": "Titular",
         "start_at": "2023-02-01T12:05", "end_at": "2023-09-13T14:53"},
        {"legislatura": 57, "condicao": "Titular",
         "start_at": "2024-12-03T10:11", "end_at": None},
    ]


def test_builders_sort_unordered_input():
    shuffled = list(reversed(ADAIL))
    got = intervals.party_intervals(shuffled)
    assert [i["sigla_partido"] for i in got] == ["REPUBLICANOS", "MDB"]
