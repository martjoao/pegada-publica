"""Build canonical senator intervals from the Senado API's dated nodes.

Unlike Câmara (which folds a ``/historico`` event stream), the Senado gives the
intervals **directly**, so these builders are straight maps:

- **office_period** — one per ``Mandato.Exercicio`` row (``DataInicio`` →
  ``DataFim``), tagged with the mandate's translated ``condition`` and the raw
  afastamento ``cause``;
- **senate_term** — one per legislature a mandate covers (an 8-year senate mandate
  spans two legislaturas), carrying UF + condition;
- **party_affiliation** — one per ``/filiacoes`` entry (``DataFiliacao`` →
  ``DataDesfiliacao``);
- **current_status** — derived (no single Senado field): ``in_office`` when present
  in ``/senador/lista/atual``, else inferred from the latest exercicio's afastamento
  cause and the mandate's legislature coverage.

All functions are pure and take raw Senado JSON nodes (PT) and return canonical
**English** keys/values (see ``docs/glossario.md``). An ``end`` of ``None`` means the
interval is still open. Dates are kept verbatim (date-only ``YYYY-MM-DD``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from common.senado_json import as_list

# Afastamento-cause sigla that means the *titular returned* (so a suplente steps
# back to being a substitute); everything else closing an interval is a leave.
_RETURN_CAUSE = "RET"


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _condition(mandato: Dict[str, Any]) -> str:
    """Translate the Senado ``DescricaoParticipacao`` to a canonical condition.

    ``Titular`` -> ``titular``; ``1º Suplente`` / ``2º Suplente`` -> ``alternate``.
    """
    desc = (mandato.get("DescricaoParticipacao") or "").strip()
    return "titular" if desc == "Titular" else "alternate"


def _legislatures(mandato: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The mandate's covered legislatures (1st and, if present, 2nd) as nodes."""
    out = []
    for key in ("PrimeiraLegislaturaDoMandato", "SegundaLegislaturaDoMandato"):
        leg = mandato.get(key)
        if leg:
            out.append(leg)
    return out


def _exercicios(mandato: Dict[str, Any]) -> List[Dict[str, Any]]:
    return as_list((mandato.get("Exercicios") or {}).get("Exercicio")
                   if mandato.get("Exercicios") else None)


def senate_terms(mandatos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One canonical term row per legislature each mandate covers (UF + condition)."""
    result: List[Dict[str, Any]] = []
    for mandato in mandatos:
        condition = _condition(mandato)
        state = mandato.get("UfParlamentar")
        for leg in _legislatures(mandato):
            result.append({
                "legislature": int(leg["NumeroLegislatura"]),
                "state": state,
                "condition": condition,
            })
    return result


def office_periods(
    mandatos: List[Dict[str, Any]], *, today: Optional[str] = None
) -> List[Dict[str, Any]]:
    """One in-office interval per exercicio, sorted by start, capped at term end.

    Each mandate's exercicios belong to its first legislature (the Senado files them
    under the mandate's start term). An open exercicio of a past legislature is capped
    at that term's end so an unclosed legacy term isn't stretched to today.
    """
    today = today or _today_iso()
    result: List[Dict[str, Any]] = []
    for mandato in mandatos:
        condition = _condition(mandato)
        legs = _legislatures(mandato)
        first = legs[0] if legs else {}
        legislature = int(first["NumeroLegislatura"]) if first else None
        term_end = first.get("DataFim")
        for ex in _exercicios(mandato):
            start = ex.get("DataInicio")
            end = ex.get("DataFim")
            if end is None and term_end is not None and term_end <= today:
                end = term_end  # unclosed past term — cap at its end
            result.append({
                "legislature": legislature,
                "condition": condition,
                "start": start,
                "end": end,
                "cause": ex.get("DescricaoCausaAfastamento"),
            })
    result.sort(key=lambda iv: iv["start"])
    return result


def party_affiliations(filiacoes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One affiliation interval per /filiacoes entry, sorted ascending by start."""
    result: List[Dict[str, Any]] = []
    for f in filiacoes:
        result.append({
            "party": f["Partido"]["SiglaPartido"],
            "start": f.get("DataFiliacao"),
            "end": f.get("DataDesfiliacao"),
            "source_note": None,
        })
    result.sort(key=lambda iv: iv["start"])
    return result


def _latest_exercicio(mandatos: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    exs = [ex for m in mandatos for ex in _exercicios(m)]
    if not exs:
        return None
    return max(exs, key=lambda ex: ex.get("DataInicio") or "")


def current_status(
    mandatos: List[Dict[str, Any]],
    *,
    in_atual: Optional[bool] = None,
    today: Optional[str] = None,
) -> Optional[str]:
    """Derive the senator's canonical current status (see module docstring).

    ``in_atual`` (presence in ``/senador/lista/atual``) may be passed explicitly; if
    left ``None`` it is derived: a senator is in exercise iff their latest exercicio
    is open (no ``DataFim``) and a mandate still covers a current legislature. (Probed
    live: the 81 ``atual`` senators are exactly those, with zero mismatches.)
    """
    today = today or _today_iso()

    # Does any mandate cover a still-current legislature?
    covers_current = any(
        (leg.get("DataFim") or "") >= today
        for m in mandatos for leg in _legislatures(m)
    )

    ex = _latest_exercicio(mandatos)

    if in_atual is None:
        in_atual = covers_current and ex is not None and ex.get("DataFim") is None
    if in_atual:
        return "in_office"

    if ex is None:
        # Never assumed. If the mandate has lapsed entirely, it ended; else unknown.
        return None if covers_current else "term_ended"

    if not covers_current:
        return "term_ended"

    # Has a current mandate and left exercise: titular returned -> substitute,
    # otherwise a leave.
    if ex.get("SiglaCausaAfastamento") == _RETURN_CAUSE:
        return "substitute"
    return "on_leave"
