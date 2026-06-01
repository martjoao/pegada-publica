# Glossário / Glossary

**Source of truth for naming across the pipeline.** The raw government APIs are in
Portuguese and the **extract** stage saves their payloads verbatim (PT) — that's
fine. From **transform** onward everything is normalized to **canonical English
identifiers** (DB tables/columns, build JSON keys, enumerated values). Portuguese
appears again only in the **site's display layer**, which maps these canonical
values to the PT labels below.

When a new term needs translating, decide it here first, then use it everywhere.
Goal: one unambiguous word per concept, so nothing is misinformed downstream.

## Entities / tables

| Canonical (EN) | PT / source concept | Meaning |
|---|---|---|
| `deputy` | deputado | A federal deputy (Câmara dos Deputados member). |
| `mandate` | mandato | A term served by a deputy in a given legislature. |
| `office_period` | exercício | A dated interval in which the deputy actually held and exercised the seat. |
| `party_affiliation` | filiação partidária | A dated interval of affiliation to a party. |
| `name_history` | histórico de nome parlamentar | Dated intervals of the parliamentary name. |
| `source` | procedência (`_meta`) | Provenance of one ingested raw landing file. |

## Columns

| Canonical (EN) | PT / source field | Meaning |
|---|---|---|
| `id` | id | Câmara deputy id; also the page URL key. |
| `deputy_id` | — | Foreign key to `deputy.id`. |
| `name` | nome | Parliamentary name (current on `deputy`, dated in `name_history`). |
| `photo_url` | urlFoto | Official photo URL. |
| `state` | UF / siglaUf | Federative unit (state) the deputy represents. |
| `legislature` | legislatura | Legislature number (56, 57). |
| `party` | siglaPartido | Party acronym (e.g. PT, PL, MDB). |
| `condition` | condiçãoEleitoral | How the seat is held — see **condition** values. |
| `start_at` / `end_at` | dataHora bounds | Interval bounds, ISO-8601 text; `end_at` null = open/ongoing. |
| `current_party` | (derived) | The deputy's current party affiliation. |
| `current_condition` | (derived) | The deputy's current `condition`. |
| `current_status` | (derived) | The deputy's current state — see **status** values. |
| `source_note` | descricaoStatus | Breadcrumb to the originating history event. |

## `condition` values (how the seat is held)

Source field: `condicaoEleitoral`.

| Canonical (EN) | Source PT | Site display (PT) | Meaning |
|---|---|---|---|
| `titular` | Titular | Titular | Directly-elected seat holder. |
| `alternate` | Suplente | Suplente | Substitute who fills in for a titular. |

## `current_status` values (the deputy's current state)

Derived from the most recent *settled* `situação` (ignoring transient `Convocado`
and metadata rows).

| Canonical (EN) | Source `situação` | Site display (PT) | Meaning |
|---|---|---|---|
| `in_office` | Exercício | Em exercício | Currently holding and exercising the seat. |
| `substitute` | Suplência | Suplente | An alternate not currently serving. |
| `on_leave` | Licença | Licenciado | Titular temporarily away (e.g. became a minister). |
| `suspended` | Suspenso | Suspenso | Suspended from the mandate. |
| `vacated` | Vacância | Mandato perdido | Lost the mandate (e.g. vote recount, court ruling). |
| `term_ended` | Fim de Mandato | Mandato encerrado | Mandate ended with the legislature. |
| `null` | — | — | No settled status (e.g. never took office). |

`in_office` (boolean, in JSON) ≡ `current_status == "in_office"`.

## Notes

- **Raw/extract stays PT.** Files under `data/raw/` mirror the API verbatim; do not
  translate them. Translation happens at the transform DB-write boundary.
- `condition` (`alternate`, a stable electoral property) and `current_status`
  (`substitute`, a current activity state) both surface as "Suplente" in PT but are
  different axes — keep them distinct in code.
