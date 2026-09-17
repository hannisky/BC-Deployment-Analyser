# Example output

What the pipeline produces for one (fictional) customer, *Nordvik Industri AB*:

| File | Produced by | Content |
|---|---|---|
| [`README.md`](./Nordvik_Industri_AB/README.md) | `orchestration/run_pipeline.py` | Customer index: every app with version in Git vs. each BC environment, links, latest changes |
| [`Nordvik_Industri_AB_Nordvik-PTE.md`](./Nordvik_Industri_AB/Nordvik_Industri_AB_Nordvik-PTE.md) | `bc-code-analyst` + `bc-change-tracker` via the orchestrator | *Anpassningar* section (H3 app → H4 features → *Övriga anpassningar*) and *Ändringshistorik* from merged PRs |
| [`Nordvik_Industri_AB_bc_Production.md`](./Nordvik_Industri_AB/Nordvik_Industri_AB_bc_Production.md) | `discovery/discover_bc_extensions.py` | Installed third-party extensions and own-app version validation (✅ / ⚠️ / ❓ / ❔) |

The AL code behind the app document is the same synthetic code used in
[`evaluation/evaluation_dataset.json`](../../evaluation/evaluation_dataset.json) (cases CA-01, CA-06, CT-02),
so you can compare the reference answers with the rendered result.
