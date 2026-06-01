"""Interval-builder tests, using the real historico transitions captured during
design (Allan Garcês 226708, Adail Filho 220714, a titular ministerial leave, a
mid-term loss of mandate). Inputs are raw PT API entries; outputs are canonical EN."""
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


# --- Allan Garcês (alternate): real subset of his 57ª history -------------
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


def test_office_periods_alternate_ignores_convocado_and_name_change():
    got = intervals.office_periods(GARCES)
    assert got == [
        {"legislature": 57, "condition": "alternate",
         "start": "2023-09-13T16:01", "end": "2024-12-03T10:11"},
        {"legislature": 57, "condition": "alternate",
         "start": "2024-12-06T17:43", "end": "2025-02-01T08:38"},
    ]


def test_name_history_tracks_parliamentary_name_change():
    got = intervals.name_history(GARCES)
    assert got == [
        {"name": "Dr. Allan Garcês", "start": "2023-02-01T00:00", "end": "2024-07-18T15:26"},
        {"name": "Allan Garcês", "start": "2024-07-18T15:26", "end": None},
    ]


def test_party_affiliations_single_party_whole_term():
    got = intervals.party_affiliations(GARCES)
    assert got == [
        {"legislature": 57, "party": "PP",
         "start": "2023-02-01T00:00", "end": None,
         "source_note": "Partido no início da legislatura / Nome no início da legislatura"},
    ]


def test_current_status_alternate_stepped_down():
    assert intervals.current_status(GARCES) == "substitute"


# --- Adail Filho (party migration REPUBLICANOS -> MDB, currently in office) ---
ADAIL = [
    _entry("2023-02-01T00:00", "REPUBLICANOS", "Adail Filho", None, None,
           "Partido no início da legislatura / Nome no início da legislatura"),
    _entry("2023-02-01T12:05", "REPUBLICANOS", "Adail Filho", "Titular", "Exercício",
           "Entrada - Posse de Eleito Titular - Posse na Sessão Preparatória"),
    _entry("2026-04-01T14:00", "MDB", "Adail Filho", "Titular", "Exercício",
           "Alteração de partido"),
]


def test_party_affiliations_captures_dated_migration():
    got = intervals.party_affiliations(ADAIL)
    assert got == [
        {"legislature": 57, "party": "REPUBLICANOS",
         "start": "2023-02-01T00:00", "end": "2026-04-01T14:00",
         "source_note": "Partido no início da legislatura / Nome no início da legislatura"},
        {"legislature": 57, "party": "MDB",
         "start": "2026-04-01T14:00", "end": None,
         "source_note": "Alteração de partido"},
    ]


def test_office_periods_titular_currently_open():
    assert intervals.office_periods(ADAIL) == [
        {"legislature": 57, "condition": "titular",
         "start": "2023-02-01T12:05", "end": None},
    ]


def test_current_status_in_office():
    assert intervals.current_status(ADAIL) == "in_office"


# --- Cross-term: same party in 56 and 57 -> two per-term intervals ----------
CROSS_TERM = [
    _entry("2019-02-01T00:00", "PSDB", "Fulano", None, None,
           "Partido no início da legislatura / Nome no início da legislatura", leg=56),
    _entry("2023-01-31T23:59", "PSDB", "Fulano", "Titular", "Fim de Mandato",
           "Saída - Afastamento definitivo - Término da Legislatura", leg=56),
    _entry("2023-02-01T00:00", "PSDB", "Fulano", None, None,
           "Partido no início da legislatura / Nome no início da legislatura", leg=57),
]


def test_party_affiliations_split_at_legislature_boundary():
    got = intervals.party_affiliations(CROSS_TERM)
    assert [(p["legislature"], p["party"], p["end"]) for p in got] == [
        (56, "PSDB", "2023-02-01T00:00"),
        (57, "PSDB", None),
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


def test_office_periods_titular_leave_and_open_tail():
    got = intervals.office_periods(TITULAR_LEAVE)
    assert got == [
        {"legislature": 57, "condition": "titular",
         "start": "2023-02-01T12:05", "end": "2023-09-13T14:53"},
        {"legislature": 57, "condition": "titular",
         "start": "2024-12-03T10:11", "end": None},
    ]


# --- Mid-term loss of mandate: situacao "Vacância" with "Diverso - … Perda de
# Mandato" (NOT "Saída -"). The interval must still close. -------------------
VACANCIA = [
    _entry("2019-02-01T11:45", "PSC", "Fulano", "Titular", "Exercício",
           "Entrada - Posse de Eleito Titular - Posse na Sessão Preparatória", leg=56),
    _entry("2020-07-01T16:27", "PL", "Fulano", "Titular", "Exercício",
           "Alteração de partido", leg=56),
    _entry("2020-11-05T00:00", "PL", "Fulano", "Não Eleito", "Vacância",
           "Diverso - Decisão da Mesa - Perda de Mandato por Recontagem de Votos", leg=56),
]


def test_office_period_closes_on_vacancia():
    got = intervals.office_periods(VACANCIA)
    assert got == [
        {"legislature": 56, "condition": "titular",
         "start": "2019-02-01T11:45", "end": "2020-11-05T00:00"},
    ]


def test_current_status_vacated():
    assert intervals.current_status(VACANCIA) == "vacated"


def test_current_status_suspended():
    suspended = [
        _entry("2023-02-01T12:05", "PSOL", "Fulano", "Titular", "Exercício",
               "Entrada - Posse de Eleito Titular"),
        _entry("2025-05-01T00:00", "PSOL", "Fulano", "Titular", "Suspenso",
               "Diverso - Suspensão do exercício do mandato"),
    ]
    assert intervals.current_status(suspended) == "suspended"


def test_current_status_none_without_settled_state():
    assert intervals.current_status([]) is None


def test_party_affiliations_cap_at_legislature_end_across_gap():
    # Served leg 51 then leg 56 (a gap in between) — the 51 affiliation must end at
    # the 51ª term end (2003), NOT stretch to 2019 (the next term served).
    gap = [
        _entry("1999-02-01T00:00", "PSDB", "X", None, None,
               "Partido no início da legislatura", leg=51),
        _entry("2019-02-01T00:00", "PSDB", "X", None, None,
               "Partido no início da legislatura", leg=56),
    ]
    got = intervals.party_affiliations(gap, today="2026-06-01T00:00")
    assert got == [
        {"legislature": 51, "party": "PSDB", "start": "1999-02-01T00:00",
         "end": "2003-02-01T00:00", "source_note": "Partido no início da legislatura"},
        {"legislature": 56, "party": "PSDB", "start": "2019-02-01T00:00",
         "end": "2023-02-01T00:00", "source_note": "Partido no início da legislatura"},
    ]


def test_builders_sort_unordered_input():
    got = intervals.party_affiliations(list(reversed(ADAIL)))
    assert [i["party"] for i in got] == ["REPUBLICANOS", "MDB"]
