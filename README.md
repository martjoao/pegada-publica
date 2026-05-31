# Pegada Pública

An open-source Brazilian congressional transparency portal. All government data already exists in official portals — this project is the glue that makes it accessible to any citizen.

## What it does

Aggregates public government data from multiple official sources, cross-references it, and serves it as a static website with zero backend cost. The one feature no other portal has: by crossing TSE campaign donor CPFs with Receita Federal company partner records (QSA), it reconstructs **inferred corporate influence** — even though corporate donations have been illegal since 2016, many top individual donors are company owners. All from public data, labeled with confidence levels.

## Data Sources

| Source | Data |
|--------|------|
| Câmara dos Deputados API | Deputies, votes, attendance, bills, speeches, CEAP expenses |
| Senado Federal API | Senators, votes, speeches, committees |
| TSE (Electoral Court) | Campaign donation records (donor CPF, value, beneficiary) |
| Receita Federal CNPJ dump | Full company registry with partner lists (QSA), updated monthly |
| Portal da Transparência | Parliamentary amendments by municipality |

## Core Entities

- **Parliamentarian** — deputies and senators, with full voting history, attendance, received donations, CEAP expenses, filed bills, amendments
- **Party** — total funding breakdown: via elected candidates, non-elected candidates, and direct party directory donations; full member history including migrations
- **Individual Donor (PF)** — total donated, beneficiary parties and parliamentarians, linked companies
- **Company** — inferred influence via partners who donated, beneficiary parliamentarians, total estimated influence with confidence tiers
- **Bill/Proposition** — tagged, searchable, with full voting record across all parliamentarians
- **Amendment** — which parliamentarian sent money to which municipality

## Key Relationships

```
Donor ──donated to──► Parliamentarian   (direct, from TSE)
Donor ──donated to──► Party             (direct, from TSE)
Donor ──is partner at──► Company        (crossed from RF QSA)
Company ──inferred influence over──► Parliamentarian  (derived)
Parliamentarian ──voted on──► Bill
Parliamentarian ──belongs to──► Party   (with start/end dates — migrations tracked)
Parliamentarian ──sent──► Amendment ──to──► Municipality
```

## Main Features

1. **Directory** — searchable/filterable list of all parliamentarians
2. **Parliamentarian profile** — votes per session (with bill context), attendance rate, received donations, CEAP expenses, filed bills, amendments by municipality
3. **Donor profile** — all beneficiary parliamentarians and parties, linked companies
4. **Company profile** — partner-donors, beneficiary parliamentarians, total inferred influence by confidence tier
5. **Party profile** — full funding breakdown, member history with party migration timeline
6. **Bills/Propositions** — tagged, full-text searchable, with voting record
7. **Voting analysis** — parliamentary proximity clustering, party discipline scores
8. **Amendment map** — geographic view of where each parliamentarian directed public money

## Architecture

Three sequential stages — no backend in production:

```
Stage 1: ETL (local)
  Python scripts → collect from APIs/dumps → process & cross-reference → local DB
  Schedule: daily (votes/attendance), weekly (expenses/amendments), monthly (company registry)

Stage 2: Static build (local)
  Build script → pre-compute every page → individual JSON files per entity + index files

Stage 3: Static site (deployed, zero cost)
  Frontend → fetch() pre-generated JSON files
  Hosted on GitHub Pages — no server, no database, no backend API
  Search runs entirely in the browser
```

The company registry (Receita Federal) requires a full monthly reload since no delta feed is available. All other sources support incremental updates.

## Scope

- Legislative terms: **56ª (2019–2023)** and **57ª (2023–present)**
- Both houses: Câmara dos Deputados and Senado Federal
- Elections: **2018** and **2022** for campaign donation data

## Legal & Ethical Notes

- All data is Brazilian government open data, explicitly published for reuse
- CPF/CNPJ cross-referencing operates on public data under LGPD Art. 7 IX (legitimate interest for social control)
- Inferred corporate influence is always labeled as an **estimate** with a confidence level (confirmed / historical / name-match only) — never as a finding of wrongdoing
- No advertising, no paid placement, no editorial bias in entity ordering

## What this is NOT

- Not a news site or editorial product — raw data, citizen draws conclusions
- Not a ranking with ideological scoring — all metrics are objective (attendance %, alignment %, total donations R$)
- Not a backend API — everything is pre-generated static files
- Not real-time — data updates on a schedule via ETL runs

## Contributing

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

To be determined.
