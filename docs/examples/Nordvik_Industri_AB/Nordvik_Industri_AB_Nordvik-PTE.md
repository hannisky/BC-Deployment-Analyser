# Nordvik PTE – Nordvik Industri AB

> **Automatiskt genererad dokumentation.** Källa: [exempelpartner/Nordvik-PTE](https://github.com/exempelpartner/Nordvik-PTE) (branch `main`, commit `f6a1b2c`) · App-version i Git: **27.3.0.0** · Utgivare: Exempelpartner · Senast uppdaterad: 2026-09-17 · Genererad av `bc-code-analyst` i Microsoft Foundry. Versionsvalidering mot Business Central finns i kundens miljörapport.

## Anpassningar

<!-- bc-analyzer:section:start -->
### Nordvik PTE
Kundspecifika anpassningar för Nordvik Industri AB. Appen är beroende av SweBase (Programekonomi Svenska AB) för kundfältet PEB External Document No.

#### Minimumorderavgift (NVK Calc Minimum Order Fee)
Funktionen lägger automatiskt till en avgiftsrad på försäljningsorder vars artikelsumma understiger ett konfigurerat minimibelopp. Inställningarna görs på sidan NVK Min. Order Fee Setup (tabellen NVK Min. Order Fee Setup) där konsulten anger Minimum Order Amount, Fee Item No. (artikeln som används för avgiften) och Fee Amount. När en order frisläpps (Release Sales Document, OnAfterReleaseSalesDoc) beräknas summan av orderns artikelrader; ligger den under minimibeloppet skapas en rad med avgiftsartikeln, kvantitet 1 och det angivna beloppet, markerad med fältet NVK Minimum Order Fee. När ordern öppnas igen (OnAfterReopenSalesDoc) tas avgiftsraden bort så att den beräknas på nytt vid nästa frisläppning. Avgiften kan även räknas om manuellt via åtgärden Recalculate Minimum Order Fee på försäljningsordersidan.

#### Kreditlimitkontroll (NVK Custom Credit Limit Mgt.)
Kundkortet har utökats med fältet NVK Custom Credit Limit, separat från standardens Credit Limit (LCY) som endast ger en varning. När en försäljningsorder frisläpps (Release Sales Document, OnBeforeReleaseSalesDoc) summeras kundens saldo i lokal valuta med orderns belopp inklusive moms; överstiger summan den egna kreditlimiten stoppas frisläppningen med ett felmeddelande som visar saldo och limit. Är fältet noll görs ingen kontroll. Fältet visas på kundkortet under gruppen Kredit.

#### Övriga anpassningar
- **Externt dokumentnummer från kund** – När en försäljningsfaktura skapas sätts External Document No. från kundfältet PEB External Document No. (SweBase) om fältet är tomt (`SetExternalDocNoFromCustomer`).
<!-- bc-analyzer:section:end -->

## Ändringshistorik

<!-- bc-analyzer:history:start -->
#### 2026-09-10 – version 27.2.0.0 → 27.3.0.0
**Nya funktioner**
- Kreditlimitkontroll: Ny codeunit NVK Custom Credit Limit Mgt. stoppar frisläppning av försäljningsorder när kundens saldo inklusive ordern överstiger det nya fältet NVK Custom Credit Limit på kundkortet, separat från standardens kreditlimit som endast varnar (PR #51)

**Tekniskt**
- Nytt beroende till SweBase 27.0.0.0 (Programekonomi Svenska AB) (commit 9999999)

#### 2026-08-01 – första dokumentation
- Dokumentationen genererades för första gången från commit `a1b2c3d`.
<!-- bc-analyzer:history:end -->
