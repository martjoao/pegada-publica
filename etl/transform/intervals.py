"""Fold a deputy's raw ``/historico`` event stream into dated intervals.

Three orthogonal timelines come out of the same event list:

- **party_affiliation** — affiliation per legislature (independent of being in office);
- **office_period** — when the deputy actually held the seat (titular or alternate);
- **name_history** — parliamentary-name changes.

Plus ``current_status`` — the deputy's current state, from the latest settled
``situação``.

All functions are pure: they take the raw ``dados`` entries (dicts straight from
the API) and return plain dicts/values with **canonical English** keys/values (see
``docs/glossario.md``). Raw PT field names/values are translated here, at the
transform boundary. An ``end`` of ``None`` means the interval is still open.

Entry fields used: ``dataHora`` (ISO timestamp, sort key), ``siglaPartido``,
``nome``, ``condicaoEleitoral``, ``situacao``, ``idLegislatura``, ``descricaoStatus``.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# Raw PT -> canonical EN value mappings (see docs/glossario.md).
CONDITION_BY_RAW = {"Titular": "titular", "Suplente": "alternate"}
STATUS_BY_SITUACAO = {
    "Exercício": "in_office",
    "Suplência": "substitute",
    "Licença": "on_leave",
    "Suspenso": "suspended",
    "Vacância": "vacated",
    "Fim de Mandato": "term_ended",
}
# situações that are neither in-office nor a settled terminal state.
_TRANSIENT_SITUACAO = {None, "Convocado"}


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


def party_affiliations(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build per-legislature party-affiliation intervals.

    A boundary occurs whenever the (legislature, party) pair changes, so a party
    held continuously across two terms yields one interval per term.
    """
    runs = _runs(entries, key=lambda e: (e["idLegislatura"], e["siglaPartido"]))
    result: List[Dict[str, Any]] = []
    for index, run in enumerate(runs):
        head = run[0]
        next_start = runs[index + 1][0]["dataHora"] if index + 1 < len(runs) else None
        result.append(
            {
                "legislature": head["idLegislatura"],
                "party": head["siglaPartido"],
                "start": head["dataHora"],
                "end": next_start,
                "source_note": head.get("descricaoStatus"),
            }
        )
    return result


def name_history(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build parliamentary-name intervals (a boundary on each name change)."""
    runs = _runs(entries, key=lambda e: e["nome"])
    result: List[Dict[str, Any]] = []
    for index, run in enumerate(runs):
        head = run[0]
        next_start = runs[index + 1][0]["dataHora"] if index + 1 < len(runs) else None
        result.append(
            {"name": head["nome"], "start": head["dataHora"], "end": next_start}
        )
    return result


def office_periods(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build in-office intervals, driven by ``situacao``.

    ``situacao == "Exercício"`` means the deputy holds the seat. An interval opens
    on the first such entry (tagged with its translated ``condition``) and closes on
    the next entry whose ``situacao`` is any *other* terminal state — Licença,
    Suplência, Fim de Mandato, Vacância, Suspenso, … A legislature change while in
    exercise also splits it. Transient ``Convocado`` / ``None`` rows are ignored, as
    are in-office party/name changes (still ``Exercício``). A final, still-open
    interval stays open (``end = None``).

    Keying on ``situacao`` (not the ``descricaoStatus`` text) matters: some exits
    (e.g. loss of mandate) are filed as ``"Diverso - … Perda de Mandato"``, which no
    ``"Saída -"`` prefix would catch.
    """
    result: List[Dict[str, Any]] = []
    open_interval: Optional[Dict[str, Any]] = None

    def _open(entry: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "legislature": entry["idLegislatura"],
            "condition": CONDITION_BY_RAW.get(
                entry["condicaoEleitoral"], entry["condicaoEleitoral"]),
            "start": entry["dataHora"],
            "end": None,
        }

    for entry in _sorted(entries):
        sit = entry.get("situacao")
        if sit == "Exercício":
            if open_interval is None:
                open_interval = _open(entry)
            elif entry["idLegislatura"] != open_interval["legislature"]:
                open_interval["end"] = entry["dataHora"]  # term changed without exit — split
                result.append(open_interval)
                open_interval = _open(entry)
            # else: still in exercise (party/name change) — same interval.
        elif sit in _TRANSIENT_SITUACAO:
            continue  # transient call-up / term-start / metadata rows
        elif open_interval is not None:
            open_interval["end"] = entry["dataHora"]  # any real exit closes it
            result.append(open_interval)
            open_interval = None
    if open_interval is not None:
        result.append(open_interval)
    return result


def current_status(entries: List[Dict[str, Any]]) -> Optional[str]:
    """The deputy's current canonical status, from the latest settled ``situacao``."""
    settled = [e for e in _sorted(entries) if e.get("situacao") not in _TRANSIENT_SITUACAO]
    if not settled:
        return None
    return STATUS_BY_SITUACAO.get(settled[-1]["situacao"])
