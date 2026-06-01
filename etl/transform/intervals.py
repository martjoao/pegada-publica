"""Fold a deputy's raw ``/historico`` event stream into dated intervals.

Three orthogonal timelines come out of the same event list:

- **party** — affiliation per legislatura (independent of being in office);
- **exercise** — when the deputy actually held the seat (Titular or Suplente);
- **name** — parliamentary-name changes.

All functions are pure: they take the raw ``dados`` entries (dicts straight from
the API) and return lists of plain interval dicts, sorted by ``start_at``. An
``end_at`` of ``None`` means the interval is still open (ongoing as of the fetch).

Entry fields used: ``dataHora`` (ISO timestamp, also the sort key), ``siglaPartido``,
``nome``, ``condicaoEleitoral``, ``idLegislatura``, ``descricaoStatus``.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


def _sorted(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(entries, key=lambda e: e["dataHora"])


def _runs(
    entries: List[Dict[str, Any]],
    key: Callable[[Dict[str, Any]], Any],
) -> List[List[Dict[str, Any]]]:
    """Group time-ordered entries into maximal runs of equal ``key``."""
    runs: List[List[Dict[str, Any]]] = []
    prev_key = object()
    for entry in _sorted(entries):
        k = key(entry)
        if k != prev_key:
            runs.append([entry])
            prev_key = k
        else:
            runs[-1].append(entry)
    return runs


def party_intervals(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build per-legislatura party-affiliation intervals.

    A boundary occurs whenever the (legislatura, party) pair changes, so a party
    held continuously across two terms yields one interval per term.
    """
    runs = _runs(entries, key=lambda e: (e["idLegislatura"], e["siglaPartido"]))
    result: List[Dict[str, Any]] = []
    for index, run in enumerate(runs):
        head = run[0]
        next_start = runs[index + 1][0]["dataHora"] if index + 1 < len(runs) else None
        result.append(
            {
                "legislatura": head["idLegislatura"],
                "sigla_partido": head["siglaPartido"],
                "start_at": head["dataHora"],
                "end_at": next_start,
                "descricao_origem": head.get("descricaoStatus"),
            }
        )
    return result


def name_intervals(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build parliamentary-name intervals (a boundary on each name change)."""
    runs = _runs(entries, key=lambda e: e["nome"])
    result: List[Dict[str, Any]] = []
    for index, run in enumerate(runs):
        head = run[0]
        next_start = runs[index + 1][0]["dataHora"] if index + 1 < len(runs) else None
        result.append(
            {"nome": head["nome"], "start_at": head["dataHora"], "end_at": next_start}
        )
    return result


# Entries whose ``situacao`` is neither in-office nor a real exit — skip them.
_EXERCISE_IGNORE = {None, "Convocado"}


def exercise_intervals(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build in-office (exercise) intervals, driven by ``situacao``.

    ``situacao == "Exercício"`` means the deputy holds the seat. An interval opens
    on the first such entry (tagged with its ``condicaoEleitoral``) and closes on the
    next entry whose ``situacao`` is any *other* terminal state — ``Licença`` (titular
    leave), ``Suplência`` (suplente step-down), ``Fim de Mandato``, ``Vacância`` (loss
    of mandate), etc. Transient ``Convocado`` call-ups and ``None`` (term-start /
    metadata) rows are ignored, as are in-office party/name changes (still
    ``Exercício``). A legislatura change while in exercise also splits the interval.
    A final, still-open interval stays open (``end_at = None``).

    Keying on ``situacao`` rather than the ``descricaoStatus`` text matters: some
    exits (e.g. loss of mandate) are filed as ``"Diverso - … Perda de Mandato"``,
    which no ``"Saída -"`` prefix would catch.
    """
    result: List[Dict[str, Any]] = []
    open_interval: Optional[Dict[str, Any]] = None
    for entry in _sorted(entries):
        sit = entry.get("situacao")
        if sit == "Exercício":
            if open_interval is None:
                open_interval = {
                    "legislatura": entry["idLegislatura"],
                    "condicao": entry["condicaoEleitoral"],
                    "start_at": entry["dataHora"],
                    "end_at": None,
                }
            elif entry["idLegislatura"] != open_interval["legislatura"]:
                # term changed without an explicit terminal entry — split.
                open_interval["end_at"] = entry["dataHora"]
                result.append(open_interval)
                open_interval = {
                    "legislatura": entry["idLegislatura"],
                    "condicao": entry["condicaoEleitoral"],
                    "start_at": entry["dataHora"],
                    "end_at": None,
                }
            # else: still in exercise (party/name change) — same interval.
        elif sit in _EXERCISE_IGNORE:
            continue  # transient call-up / term-start / metadata rows
        elif open_interval is not None:
            open_interval["end_at"] = entry["dataHora"]  # any real exit closes it
            result.append(open_interval)
            open_interval = None
    if open_interval is not None:
        result.append(open_interval)
    return result
