"""Senado interval-builder tests, using the real shapes probed live 2026-06-01
(Alan Rick 5672 filiacoes, Ana Paula Lobato 6358 suplente exercicios, the 8-year
two-legislature mandate). Inputs are raw PT API nodes; outputs are canonical EN."""
from transform import senado_intervals as si


# --- office_periods: from Mandato.Exercicios -------------------------------
def test_office_periods_open_titular_currently_serving():
    mandato = {
        "DescricaoParticipacao": "Titular",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "57", "DataFim": "2027-01-31"},
        "Exercicios": {"Exercicio": {"DataInicio": "2023-02-01"}},
    }
    assert si.office_periods([mandato], today="2026-06-01") == [
        {"legislature": 57, "condition": "titular",
         "start": "2023-02-01", "end": None, "cause": None},
    ]


def test_office_periods_closed_by_datafim_and_cause():
    mandato = {
        "DescricaoParticipacao": "1º Suplente",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "57", "DataFim": "2027-01-31"},
        "Exercicios": {"Exercicio": [
            {"DataInicio": "2024-02-21"},
            {"DataInicio": "2023-02-02", "DataFim": "2024-01-31",
             "SiglaCausaAfastamento": "RET", "DescricaoCausaAfastamento": "Retorno do titular"},
        ]},
    }
    got = si.office_periods([mandato], today="2026-06-01")
    # sorted by start; the alternate condition; the closed interval carries its cause
    assert got == [
        {"legislature": 57, "condition": "alternate",
         "start": "2023-02-02", "end": "2024-01-31", "cause": "Retorno do titular"},
        {"legislature": 57, "condition": "alternate",
         "start": "2024-02-21", "end": None, "cause": None},
    ]


def test_office_periods_caps_open_interval_of_past_legislature_at_term_end():
    mandato = {
        "DescricaoParticipacao": "Titular",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "55", "DataFim": "2019-01-31"},
        "Exercicios": {"Exercicio": {"DataInicio": "2015-02-01"}},
    }
    # An unclosed legacy term must end at its term end, not stretch to today.
    assert si.office_periods([mandato], today="2026-06-01") == [
        {"legislature": 55, "condition": "titular",
         "start": "2015-02-01", "end": "2019-01-31", "cause": None},
    ]


def test_office_periods_suplente_never_served_is_empty():
    mandato = {
        "DescricaoParticipacao": "1º Suplente",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "57", "DataFim": "2027-01-31"},
        "Exercicios": None,
    }
    assert si.office_periods([mandato], today="2026-06-01") == []


# --- senate_terms: one row per covered legislature ------------------------
def test_senate_terms_spans_two_legislatures():
    mandato = {
        "UfParlamentar": "AC",
        "DescricaoParticipacao": "Titular",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "57"},
        "SegundaLegislaturaDoMandato": {"NumeroLegislatura": "58"},
    }
    assert si.senate_terms([mandato]) == [
        {"legislature": 57, "state": "AC", "condition": "titular"},
        {"legislature": 58, "state": "AC", "condition": "titular"},
    ]


def test_senate_terms_dedups_same_legislature_preferring_titular():
    # A senator holding two mandates covering leg 56 (one titular, one suplente)
    # must collapse to a single titular row for that legislature.
    mandatos = [
        {"UfParlamentar": "CE", "DescricaoParticipacao": "1º Suplente",
         "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "55"},
         "SegundaLegislaturaDoMandato": {"NumeroLegislatura": "56"}},
        {"UfParlamentar": "CE", "DescricaoParticipacao": "Titular",
         "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "56"},
         "SegundaLegislaturaDoMandato": {"NumeroLegislatura": "57"}},
    ]
    terms = si.senate_terms(mandatos)
    assert [t["legislature"] for t in terms] == [55, 56, 57]
    assert {t["legislature"]: t["condition"] for t in terms} == {
        55: "alternate", 56: "titular", 57: "titular"}


def test_senate_terms_suplente_condition_maps_to_alternate():
    mandato = {
        "UfParlamentar": "BA",
        "DescricaoParticipacao": "1º Suplente",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "55"},
        "SegundaLegislaturaDoMandato": {"NumeroLegislatura": "56"},
    }
    terms = si.senate_terms([mandato])
    assert {t["condition"] for t in terms} == {"alternate"}
    assert [t["legislature"] for t in terms] == [55, 56]


# --- party_affiliations: from /filiacoes -----------------------------------
ALAN_RICK = [
    {"Partido": {"SiglaPartido": "REPUBLICANOS"}, "DataFiliacao": "2025-11-12"},
    {"Partido": {"SiglaPartido": "UNIÃO"}, "DataFiliacao": "2022-02-24",
     "DataDesfiliacao": "2025-11-10"},
    {"Partido": {"SiglaPartido": "DEM"}, "DataFiliacao": "2017-08-01",
     "DataDesfiliacao": "2022-02-23"},
]


def test_party_affiliations_dated_open_and_closed():
    got = si.party_affiliations(ALAN_RICK)
    # sorted ascending by start; open affiliation has end None
    assert got == [
        {"party": "DEM", "start": "2017-08-01", "end": "2022-02-23",
         "source_note": None},
        {"party": "UNIÃO", "start": "2022-02-24", "end": "2025-11-10",
         "source_note": None},
        {"party": "REPUBLICANOS", "start": "2025-11-12", "end": None,
         "source_note": None},
    ]


def test_party_affiliations_single_filiacao():
    got = si.party_affiliations([
        {"Partido": {"SiglaPartido": "PT"}, "DataFiliacao": "2022-10-02"}])
    assert got == [{"party": "PT", "start": "2022-10-02", "end": None,
                    "source_note": None}]


def test_party_affiliations_empty():
    assert si.party_affiliations([]) == []


# --- current_status: derived ----------------------------------------------
def test_current_status_in_office_when_in_atual():
    assert si.current_status([], in_atual=True) == "in_office"


def test_current_status_derives_in_office_from_open_current_exercicio():
    # in_atual omitted -> derived: latest exercicio open + current term => in_office.
    mandato = {
        "DescricaoParticipacao": "Titular",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "57", "DataFim": "2027-01-31"},
        "Exercicios": {"Exercicio": {"DataInicio": "2023-02-01"}},
    }
    assert si.current_status([mandato], today="2026-06-01") == "in_office"


def test_current_status_on_leave_when_left_by_leave_cause():
    mandato = {
        "DescricaoParticipacao": "Titular",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "57", "DataFim": "2027-01-31"},
        "Exercicios": {"Exercicio": {"DataInicio": "2023-02-01", "DataFim": "2024-05-01",
                                     "SiglaCausaAfastamento": "AFO",
                                     "DescricaoCausaAfastamento": "Afastamento do exercício"}},
    }
    assert si.current_status([mandato], in_atual=False, today="2026-06-01") == "on_leave"


def test_current_status_substitute_when_titular_returned():
    mandato = {
        "DescricaoParticipacao": "1º Suplente",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "57", "DataFim": "2027-01-31"},
        "Exercicios": {"Exercicio": {"DataInicio": "2023-02-02", "DataFim": "2024-01-31",
                                     "SiglaCausaAfastamento": "RET",
                                     "DescricaoCausaAfastamento": "Retorno do titular"}},
    }
    assert si.current_status([mandato], in_atual=False, today="2026-06-01") == "substitute"


def test_current_status_term_ended_when_only_past_legislatures():
    mandato = {
        "DescricaoParticipacao": "Titular",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "55", "DataFim": "2019-01-31"},
        "SegundaLegislaturaDoMandato": {"NumeroLegislatura": "56", "DataFim": "2023-01-31"},
        "Exercicios": {"Exercicio": {"DataInicio": "2015-02-01"}},
    }
    assert si.current_status([mandato], in_atual=False, today="2026-06-01") == "term_ended"


def test_current_status_null_when_no_exercicio_in_current_term():
    mandato = {
        "DescricaoParticipacao": "2º Suplente",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "57", "DataFim": "2027-01-31"},
        "Exercicios": None,
    }
    assert si.current_status([mandato], in_atual=False, today="2026-06-01") is None
