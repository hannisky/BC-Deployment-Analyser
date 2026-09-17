# Implementationsdokumentation Nordvik Industri AB

> Automatiskt underhållen av BC Deployment Analyzer. Senast körd: 2026-09-17. Varje app har ett eget dokument med funktionsbeskrivning (Anpassningar) och ändringshistorik. Installerade tredjepartstillägg och versionsvalidering per Business Central-miljö finns i miljörapporterna nedan.

## Egna anpassningar (PTE)

| App | GitHub-repo | Version (Git) | Version (BC Production) | Version (BC Sandbox) | Dokumentation | Senast dokumenterad |
|---|---|---|---|---|---|---|
| Nordvik API PTE | [Nordvik-API-PTE](https://github.com/exempelpartner/Nordvik-API-PTE) | 27.0.0.0 | ✅ 27.0.0 | ✅ 27.0.0 | [Nordvik_Industri_AB_Nordvik-API-PTE.md](./Nordvik_Industri_AB_Nordvik-API-PTE.md) | 2026-09-02 |
| Nordvik Currency Clause | [Nordvik-Currency-PTE](https://github.com/exempelpartner/Nordvik-Currency-PTE) | 26.0.0.1 | ❔ ej publicerad | ❔ ej publicerad | [Nordvik_Industri_AB_Nordvik-Currency-PTE.md](./Nordvik_Industri_AB_Nordvik-Currency-PTE.md) | 2026-09-02 |
| Nordvik PTE | [Nordvik-PTE](https://github.com/exempelpartner/Nordvik-PTE) | 27.3.0.0 | ⚠️ 27.2.0 | ✅ 27.3.0 | [Nordvik_Industri_AB_Nordvik-PTE.md](./Nordvik_Industri_AB_Nordvik-PTE.md) | 2026-09-17 |
| Nordvik Purchase PTE | [Nordvik-Purchase-PTE](https://github.com/exempelpartner/Nordvik-Purchase-PTE) | 27.1.0.0 | ✅ 27.1.0 | ✅ 27.1.0 | [Nordvik_Industri_AB_Nordvik-Purchase-PTE.md](./Nordvik_Industri_AB_Nordvik-Purchase-PTE.md) | 2026-09-02 |
| Nordvik Sales PTE | [Nordvik-Sales-PTE](https://github.com/exempelpartner/Nordvik-Sales-PTE) | 27.0.4.0 | ✅ 27.0.4 | ✅ 27.0.4 | [Nordvik_Industri_AB_Nordvik-Sales-PTE.md](./Nordvik_Industri_AB_Nordvik-Sales-PTE.md) | 2026-09-12 |

Inaktiva/arkiverade repos: `Nordvik-Legacy-Reports`

## Business Central-miljöer

- [Production](./Nordvik_Industri_AB_bc_Production.md) – 4 tredjepartstillägg, 5 egna appar (3 ✅, 1 ⚠️, 1 ❓) · inventerad 2026-09-17
- [Sandbox](./Nordvik_Industri_AB_bc_Sandbox.md) – 4 tredjepartstillägg, 5 egna appar (4 ✅, 0 ⚠️, 1 ❓) · inventerad 2026-09-17

## Senaste ändringar

- **2026-09-17 – Nordvik-PTE** (v27.3.0.0): Ny kreditlimitkontroll som stoppar frisläppning av order när kundens saldo överstiger en egen kreditlimit; nytt beroende till SweBase.
- **2026-09-12 – Nordvik-Sales-PTE** (v27.0.4.0): Endast versionsuppräkning till 27.0.4.0 och uppdaterade pipeline-filer; ingen funktionell ändring.
