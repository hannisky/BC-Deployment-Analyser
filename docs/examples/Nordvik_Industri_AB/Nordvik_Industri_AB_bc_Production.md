# Installerade tillägg – Nordvik Industri AB (Production)

> Automatiskt genererad av `discover_bc_extensions.py` 2026-09-17. Tenant `11111111-2222-3333-4444-555555555555`, miljö **Production**, företag *Nordvik Industri AB*. Källa: Business Central Automation API (`publisher ne 'Microsoft'`). Versionsvalidering mot GitHub-inventeringen från `discover_repos.py` (2026-09-17T02:14:09Z).

## Sammanfattning

| Kategori | Antal |
|---|---:|
| Tredjepartstillägg (ISV) | 4 |
| Egna appar publicerade i miljön | 5 |
| ✅ Version matchar Git | 3 |
| ⚠️ Versionsavvikelse | 1 |
| ❓ Publicerad app utan repo | 1 |
| ❔ Repo utan publicerad app | 1 |

## 1 Installerade tillägg (tredje part)

Kommersiella ISV-appar installerade i miljön. Beskrivningar hämtas från `known_extensions.json` när de finns.

| Tillägg | Utgivare | Version | Status | Beskrivning |
|---|---|---|---|---|
| ExFlow - Accounts Payable Automation | SignUp Software AB | 27.1.85 | Installerad | Leverantörsfakturahantering med attestflöde. Används för alla inköpsfakturor. Mer information: https://www.exflow.com |
| ExFlow License Provider | SignUp Software AB | 24.1.40 | Installerad | – |
| Golden EDI | Golden EDI AB | 28.5.159 | Installerad | EDI-kommunikation med större kunder (order in, faktura ut). Mer information: https://goldenedi.se |
| SweBase | Programekonomi Svenska AB | 28.3.256 | Installerad | Svensk lokaliseringsbas (bl.a. PEB External Document No. som Nordvik PTE använder). |

## 2 Egna anpassningar – versionsvalidering

Appar publicerade under egen utgivare jämförda med `app.json` i respektive repos standardbranch (jämförelse på major.minor.build). Detaljerad funktionsdokumentation per app finns i respektive app-dokument.

| App | GitHub-repo | Version i BC | Version i Git | Status |
|---|---|---|---|---|
| Nordvik API PTE | [Nordvik-API-PTE](https://github.com/exempelpartner/Nordvik-API-PTE) | 27.0.0 | 27.0.0.0 | ✅ Matchar |
| Nordvik Legacy Reports | – | 25.0.0 | – | ❓ Inget repo hittades |
| Nordvik PTE | [Nordvik-PTE](https://github.com/exempelpartner/Nordvik-PTE) | 27.2.0 | 27.3.0.0 | ⚠️ Git är nyare – ej publicerad ändring |
| Nordvik Purchase PTE | [Nordvik-Purchase-PTE](https://github.com/exempelpartner/Nordvik-Purchase-PTE) | 27.1.0 | 27.1.0.0 | ✅ Matchar |
| Nordvik Sales PTE | [Nordvik-Sales-PTE](https://github.com/exempelpartner/Nordvik-Sales-PTE) | 27.0.4 | 27.0.4.0 | ✅ Matchar |

## 3 Repos utan publicerad app i miljön

AL-projekt i GitHub som inte motsvarar någon installerad app i just denna miljö (kan vara under utveckling, publicerad i en annan miljö eller avvecklad).

| GitHub-repo | App (app.json) | Version i Git | Status |
|---|---|---|---|
| [Nordvik-Currency-PTE](https://github.com/exempelpartner/Nordvik-Currency-PTE) | Nordvik Currency Clause | 26.0.0.1 | ❔ Ej publicerad i miljön |
