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
| `senator` | senador | A senator (Senado Federal member). |
| `senate_term` | mandato (senador) | A senator's mandate within a given legislature; the Senado 8-year mandate spans two legislatures, so one row per covered legislature (carries UF + condition). |
| `senator_office_period` | exercício (senador) | A dated interval a senator actually held the seat, from a `Mandato.Exercicio` row. |
| `senator_party_affiliation` | filiação partidária (senador) | A dated party affiliation, from `/filiacoes` (`DataFiliacao`/`DataDesfiliacao`). |
| `senator_name_history` | histórico de nome parlamentar (senador) | Dated parliamentary-name intervals (rarely changes; usually one open interval). |
| `tse_candidate` | candidato TSE | A federal candidate in a TSE election year. |
| `donor` | doador | A unique campaign donor, deduplicated by CPF/CNPJ. |
| `tse_donation` | receita eleitoral | A single campaign donation record from TSE `receitas_candidatos`. |

## Columns

| Canonical (EN) | PT / source field | Meaning |
|---|---|---|
| `id` | id / CodigoParlamentar | Câmara deputy id, or Senado `CodigoParlamentar`; also the page URL key. |
| `deputy_id` | — | Foreign key to `deputy.id`. |
| `senator_id` | CodigoParlamentar | Foreign key to `senator.id`. |
| `cause` | DescricaoCausaAfastamento | Why a senator's office period ended (raw PT kept; e.g. "Retorno do titular"). |
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
| `office` | cargo / DS_CARGO | The elected office sought: `federal_deputy`, `senator`, or `president`. |
| `election_result` | DS_SIT_TOT_TURNO | Final election outcome: `elected`, `not_elected`, `alternate`, `invalidated`, `withdrew`, `pending`, or NULL. |
| `funding_source` | DS_FONTE_RECEITA | Canonical donation source type: `individual_donation`, `self_funding`, `party_transfer`, `electoral_fund`, `party_fund`, `candidate_transfer`, or `other`. |
| `donor_type` | (derived) | `individual` (CPF, 11 digits), `company` (CNPJ, 14 digits), `party` (no CPF), `unknown` (other length). |

## Bio columns (`deputy` and `senator`)

Populated by `transform/camara/deputados.py` and `transform/senado/senadores.py` from the bio landing files.

| Canonical (EN) | Deputy source (PT) | Senator source (PT) | Meaning |
|---|---|---|---|
| `cpf` | `cpf` | — (not in Senado API) | Tax ID; internal only — LGPD-protected; never exported to build JSON. |
| `civil_name` | `nomeCivil` | `NomeCompletoParlamentar` | Full legal name (different from parliamentary name). |
| `date_of_birth` | `dataNascimento` | `DadosBasicosParlamentar.DataNascimento` | ISO-8601 date. |
| `date_of_death` | `dataFalecimento` | — | ISO-8601 date; NULL if alive. Deputy only. |
| `sex` | `sexo` (already `'M'`/`'F'`) | `SexoParlamentar` (normalized `'Masculino'`→`'M'`, `'Feminino'`→`'F'`) | `'M'` or `'F'`. |
| `birth_state` | `ufNascimento` | `UfNaturalidade` | UF sigla. |
| `birth_city` | `municipioNascimento` | `Naturalidade` | City name. |
| `education` | `escolaridade` | — | Education level string. Deputy only. |
| `social_media` | `redeSocial` (list serialized as JSON string) | — | JSON array of URLs. Deputy only. |
| `website` | `urlWebsite` | — | Personal website URL. Deputy only. |
| `email` | — | `EmailParlamentar` | Official senate email. Senator only. |

## `condition` values (how the seat is held)

Source field: `condicaoEleitoral`.

| Canonical (EN) | Source PT | Site display (PT) | Meaning |
|---|---|---|---|
| `titular` | Titular | Titular | Directly-elected seat holder. |
| `alternate` | Suplente / `Nº Suplente` | Suplente | Substitute who fills in for a titular. (Senado `DescricaoParticipacao` is `1º Suplente` / `2º Suplente`; both map to `alternate`.) |

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

**Senators** share this enum, but it is *derived* (no single Senado field):
`in_office` = present in `/senador/lista/atual`; `on_leave` / `substitute` inferred
from the latest exercicio's `DescricaoCausaAfastamento` (leave-type cause → `on_leave`;
`RET` "Retorno do titular" for a suplente → `substitute`); `term_ended` = mandate
covers only past legislatures; `null` = a mandate with no exercicio (never assumed).
`suspended` / `vacated` are not currently produced for senators (no clean signal).

## Notes

- **Raw/extract stays PT.** Files under `data/raw/` mirror the API verbatim; do not
  translate them. Translation happens at the transform DB-write boundary.
- `condition` (`alternate`, a stable electoral property) and `current_status`
  (`substitute`, a current activity state) both surface as "Suplente" in PT but are
  different axes — keep them distinct in code.
