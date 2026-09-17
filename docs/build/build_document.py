"""
docs/build/build_document.py — Build the course deliverable "BC Deployment Analyzer — Solution Design"
as a Word document (and PDF when Microsoft Word is installed) from the content of this repository.

Usage:
    python docs/build/render_diagrams.py     # first: renders docs/diagrams/*.png
    python docs/build/build_document.py      # writes docs/BC_Deployment_Analyzer_Solution_Design.docx (+ .pdf)
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[2]
DIAGRAMS = ROOT / "docs" / "diagrams"
OUT_DOCX = ROOT / "docs" / "BC_Deployment_Analyzer_Solution_Design.docx"

NAVY = RGBColor(0x0D, 0x1B, 0x35)
BLUE = RGBColor(0x1E, 0x5C, 0xC8)
GREY = RGBColor(0x59, 0x60, 0x6E)
HEADER_FILL = "1E5CC8"
ALT_FILL = "EEF3FB"
CODE_FILL = "F3F4F6"


# =============================================================================================
# Low-level helpers
# =============================================================================================
def shade(cell, hex_fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def set_cell_text(cell, text: str, bold: bool = False, color: RGBColor | None = None, size: int = 9) -> None:
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    add_inline_runs(p, text, bold=bold, color=color, size=size)


def add_inline_runs(paragraph, text: str, bold: bool = False, color: RGBColor | None = None, size: int | None = None) -> None:
    """Supports `code` spans and **bold** spans inside a paragraph."""
    import re

    parts = re.split(r"(`[^`]+`|\*\*[^*]+\*\*)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt((size or 10) - 1)
            run.font.color.rgb = RGBColor(0x8B, 0x1A, 0x5E)
        elif part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        else:
            run = paragraph.add_run(part)
            run.bold = bold
        if color is not None:
            run.font.color.rgb = color
        if size and not (part.startswith("`")):
            run.font.size = Pt(size)


class Doc:
    def __init__(self):
        self.d = Document()
        self._styles()
        sec = self.d.sections[0]
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        for side in ("left_margin", "right_margin"):
            setattr(sec, side, Cm(2.2))
        sec.top_margin, sec.bottom_margin = Cm(2.0), Cm(2.0)
        self._footer(sec)

    def _styles(self):
        st = self.d.styles
        st["Normal"].font.name = "Calibri"
        st["Normal"].font.size = Pt(10.5)
        st["Normal"].paragraph_format.space_after = Pt(6)
        for name, size, color in (("Heading 1", 18, NAVY), ("Heading 2", 14, BLUE), ("Heading 3", 12, NAVY)):
            s = st[name]
            s.font.name = "Calibri"
            s.font.size = Pt(size)
            s.font.bold = True
            s.font.color.rgb = color
            s.paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
            s.paragraph_format.space_after = Pt(4)
            rpr = s.element.get_or_add_rPr()
            rfonts = rpr.find(qn("w:rFonts"))
            if rfonts is None:
                rfonts = OxmlElement("w:rFonts")
                rpr.append(rfonts)
            rfonts.set(qn("w:asciiTheme"), "")
            rfonts.set(qn("w:ascii"), "Calibri")
            rfonts.set(qn("w:hAnsi"), "Calibri")

    def _footer(self, section):
        p = section.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("BC Deployment Analyzer — Solution Design · ")
        run.font.size = Pt(8)
        run.font.color.rgb = GREY
        # page number field
        for tag, text in (("begin", None), (None, "PAGE"), ("end", None)):
            r = p.add_run()
            r.font.size = Pt(8)
            r.font.color.rgb = GREY
            if tag:
                fld = OxmlElement("w:fldChar")
                fld.set(qn("w:fldCharType"), tag)
                r._r.append(fld)
            else:
                instr = OxmlElement("w:instrText")
                instr.set(qn("xml:space"), "preserve")
                instr.text = text
                r._r.append(instr)

    # --- content --------------------------------------------------------------------------------
    def h1(self, text):
        return self.d.add_heading(text, level=1)

    def h2(self, text):
        return self.d.add_heading(text, level=2)

    def h3(self, text):
        return self.d.add_heading(text, level=3)

    def p(self, text: str, italic: bool = False, size: int | None = None, color: RGBColor | None = None, align=None):
        para = self.d.add_paragraph()
        add_inline_runs(para, text, color=color, size=size)
        if italic:
            for r in para.runs:
                r.italic = True
        if align:
            para.alignment = align
        return para

    def bullets(self, items: list[str], numbered: bool = False):
        style = "List Number" if numbered else "List Bullet"
        for item in items:
            para = self.d.add_paragraph(style=style)
            para.paragraph_format.space_after = Pt(2)
            add_inline_runs(para, item)

    def code(self, text: str):
        table = self.d.add_table(rows=1, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = table.cell(0, 0)
        shade(cell, CODE_FILL)
        cell.text = ""
        first = True
        for line in text.strip("\n").splitlines():
            para = cell.paragraphs[0] if first else cell.add_paragraph()
            first = False
            para.paragraph_format.space_after = Pt(0)
            run = para.add_run(line)
            run.font.name = "Consolas"
            run.font.size = Pt(8.5)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)

    def table(self, header: list[str], rows: list[list[str]], widths_cm: list[float] | None = None, size: int = 9):
        table = self.d.add_table(rows=1, cols=len(header))
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, h in enumerate(header):
            cell = table.rows[0].cells[i]
            shade(cell, HEADER_FILL)
            set_cell_text(cell, h, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF), size=size)
        for r_idx, row in enumerate(rows):
            cells = table.add_row().cells
            for i, value in enumerate(row):
                set_cell_text(cells[i], value, size=size)
                if r_idx % 2 == 1:
                    shade(cells[i], ALT_FILL)
        if widths_cm:
            for row in table.rows:
                for i, w in enumerate(widths_cm):
                    row.cells[i].width = Cm(w)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)
        return table

    def figure(self, name: str, caption: str, width_cm: float = 16.6):
        path = DIAGRAMS / f"{name}.png"
        if not path.exists():
            self.p(f"[diagram {name} missing — run docs/build/render_diagrams.py]", italic=True, color=GREY)
            return
        para = self.d.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_after = Pt(2)
        para.add_run().add_picture(str(path), width=Cm(width_cm))
        cap = self.d.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = cap.add_run(caption)
        run.italic = True
        run.font.size = Pt(9)
        run.font.color.rgb = GREY

    def page_break(self):
        self.d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def landscape_section(self):
        sec = self.d.add_section()
        sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = Cm(29.7), Cm(21.0)
        sec.left_margin = sec.right_margin = Cm(1.5)
        sec.top_margin = sec.bottom_margin = Cm(1.5)
        return sec

    def portrait_section(self):
        sec = self.d.add_section()
        sec.orientation = WD_ORIENT.PORTRAIT
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        sec.left_margin = sec.right_margin = Cm(2.2)
        sec.top_margin = sec.bottom_margin = Cm(2.0)
        return sec

    def toc(self):
        para = self.d.add_paragraph()
        run = para.add_run()
        for tag, text in (("begin", None), (None, 'TOC \\o "1-2" \\h \\z \\u'), ("separate", None), (None, None), ("end", None)):
            if tag:
                fld = OxmlElement("w:fldChar")
                fld.set(qn("w:fldCharType"), tag)
                run._r.append(fld)
            elif text:
                instr = OxmlElement("w:instrText")
                instr.set(qn("xml:space"), "preserve")
                instr.text = text
                run._r.append(instr)
            else:
                t = OxmlElement("w:t")
                t.text = "Right-click → Update Field to build the table of contents."
                run._r.append(t)
        # Ask Word to refresh fields when the file is opened
        settings = self.d.settings.element
        upd = OxmlElement("w:updateFields")
        upd.set(qn("w:val"), "true")
        settings.append(upd)


# =============================================================================================
# Content
# =============================================================================================
def build() -> Path:
    doc = Doc()
    d = doc.d

    # --- Title page ----------------------------------------------------------------------------
    for _ in range(6):
        d.add_paragraph()
    t = d.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("BC Deployment Analyzer")
    r.font.size, r.bold, r.font.color.rgb = Pt(30), True, NAVY
    s = d.add_paragraph()
    s.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = s.add_run("A production-ready multi-agent documentation pipeline for\nBusiness Central Per-Tenant Extensions on Microsoft Foundry")
    r.font.size, r.font.color.rgb = Pt(14), BLUE
    d.add_paragraph()
    m = d.add_paragraph()
    m.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = m.add_run("Solution design · Agent architecture · Observability · Evaluation · Workflow")
    r.font.size, r.font.color.rgb = Pt(11), GREY
    for _ in range(8):
        d.add_paragraph()
    meta = d.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = meta.add_run(
        "Build and Scale AI Agents with Microsoft Foundry — Level 3: Architect\n"
        "Final assignment · Hannes K, Information & Business Solutions Svenska AB (InBiz)\n"
        f"{date.today().isoformat()} · Repository: github.com/hannisky/BC-Deployment-Analyser"
    )
    r.font.size, r.font.color.rgb = Pt(10), GREY
    doc.page_break()

    doc.h1("Contents")
    doc.toc()
    doc.page_break()

    # --- Executive summary -------------------------------------------------------------------------
    doc.h1("Executive summary")
    doc.p(
        "A Microsoft Dynamics 365 Business Central partner maintains dozens of customer-specific extensions "
        "(Per-Tenant Extensions, PTEs) in GitHub. The knowledge of what those extensions do, which version is live in "
        "each customer environment, and what changed last sprint lives in AL source code and in developers' heads. "
        "Hand-written implementation documents go stale the day after they are written."
    )
    doc.p(
        "The BC Deployment Analyzer keeps that documentation alive automatically. Deterministic Python discovery "
        "inventories the customer's repositories and Business Central environments and validates published versions "
        "against source control. Two specialised Microsoft Foundry agents then collaborate: **bc-change-tracker** reads "
        "the pull requests merged since the last run and rates the documentation impact; **bc-code-analyst** reads the "
        "AL source through a deterministic analysis tool and writes — or surgically updates — the Swedish "
        "\"Anpassningar\" documentation for each app. The Markdown lands in GitHub, the Microsoft 365 Copilot GitHub "
        "connector indexes it, and consultants ask Copilot instead of reading code."
    )
    doc.p(
        "The solution productionises an existing proof of concept (one plain OpenAI call per repository, no tracing, no "
        "evaluation) using the lifecycle taught in the course: setup → build agents → monitor → evaluate → orchestrate. "
        "Every phase is implemented as runnable code in the repository; this document describes the design decisions "
        "behind it."
    )
    doc.table(
        ["Course requirement", "Where it is addressed"],
        [
            ["Business problem, users, ≥2 agents, tools/data, why multi-agent", "Section 1 — Solution design"],
            ["Observability strategy", "Section 2.1"],
            ["Evaluation strategy", "Section 2.2"],
            ["Governance and reliability", "Section 2.3"],
            ["End-to-end workflow: sequence, information passed, tool calls, output, operations", "Section 3"],
            ["Reflection: prototype → production", "Section 4"],
        ],
        widths_cm=[9.5, 7.1],
    )

    # --- Architecture figure (landscape) ------------------------------------------------------------
    doc.landscape_section()
    doc.h1("Architecture at a glance")
    doc.figure("architecture", "Figure 1 — End-to-end architecture: GitHub and Business Central feed deterministic discovery and the two Foundry agents; output is indexed by Microsoft 365 Copilot; traces flow to Application Insights; evaluation runs against a versioned dataset.", width_cm=26.5)
    doc.p(
        "Reading the figure left to right: a developer merges a pull request in a customer repository. Discovery (plain "
        "Python) refreshes the repository inventory and queries Business Central. Inside Microsoft Foundry the change "
        "tracker hands an impact verdict and changelog to the code analyst, which produces the Swedish documentation "
        "section. Every agent run is traced to Application Insights and Log Analytics; the evaluation dataset scores the "
        "agents before each release. The generated Markdown is committed to GitHub and surfaced to consultants through "
        "Microsoft 365 Copilot.",
        size=10,
    )
    doc.portrait_section()

    # =============================================================================================
    doc.h1("1. Solution design")
    doc.h2("1.1 Business problem")
    doc.p(
        "The partner develops and operates customer-specific extensions for Business Central. Each customer has three to "
        "ten GitHub repositories of AL code and one or more Business Central environments (production, sandbox). Four "
        "recurring problems motivated the solution:"
    )
    doc.bullets(
        [
            "**Knowledge is locked in code.** Only the developer who wrote a codeunit knows what it does. Support consultants either read AL or ask around.",
            "**Documentation decays.** The partner's hand-written *Implementationsdokumentation* (installed extensions, process descriptions, customisations) is accurate on the day it is written. A real reference document was missing an entire feature (`CustomCreditLimitMgt`) that existed in the repository.",
            "**Nobody knows what is live.** Whether the version in `main` is the version installed in the customer's production environment is checked manually, if at all — a source of surprises during upgrades.",
            "**Change history is invisible to non-developers.** Merged pull requests explain *why* something changed, but consultants never see them.",
        ]
    )
    doc.p(
        "The measurable goal: every customer app has current Swedish documentation within one day of a merged pull "
        "request, every published version is validated against source control, and consultants can answer "
        "\"how does X work at customer Y\" from Copilot without reading code."
    )

    doc.h2("1.2 Intended users")
    doc.table(
        ["User", "Needs", "Touchpoint"],
        [
            ["Support / application consultants", "\"How does the minimum order fee work at Nordvik?\" · \"Which apps does customer X have and are they up to date?\"", "Microsoft 365 Copilot chat (GitHub connector indexes the generated Markdown), or the Markdown directly in GitHub"],
            ["Project managers / customer leads", "Release notes per customer per sprint in plain Swedish", "*Ändringshistorik* section per app; *Senaste ändringar* on the customer index page"],
            ["Developers", "Zero extra work; a safety net that flags unpublished versions and undocumented objects", "Nothing to do — merging a PR triggers the update"],
            ["Operations (partner IT)", "Cost, failures and quality of the pipeline", "Application Insights dashboards, KQL queries, evaluation reports"],
        ],
        widths_cm=[3.6, 6.8, 6.2],
    )

    doc.h2("1.3 The agents")
    doc.figure("agents", "Figure 2 — The two agents, their tools and instruction files inside the Foundry project. The tracker's verdict feeds the analyst's update mode.", width_cm=16.6)
    doc.table(
        ["", "bc-change-tracker", "bc-code-analyst"],
        [
            ["Responsibility", "Explain what changed in a repository between two commits and rate how much of the documentation is affected", "Describe what an AL app does for consultants, in Swedish, following the partner's documentation standard"],
            ["Question answered", "What changed since we last documented this, and does it matter?", "What does this app do, today?"],
            ["Tool (FunctionTool)", "`get_repo_changes(org, repo, base_sha, head_sha)`", "`analyze_repo(org, repo, branch)`"],
            ["Input size", "Small — a diff, PR titles/bodies, patches", "Large — a whole PTE repository"],
            ["Output contract", "JSON verdict (`impact: none/minor/major`, `affected_features`, `new_objects`, `requires_full_regeneration`, `summary_sv`) + Swedish changelog entry", "`### App` → `#### Feature (AL object)` → `#### Övriga anpassningar` Markdown section; **full** or **update** mode"],
            ["Instructions", "`agents/instructions/change_tracker.md`", "`agents/instructions/code_analyst.md`"],
            ["Model", "gpt-5.4 (GlobalStandard deployment in the Foundry project)", "gpt-5.4"],
        ],
        widths_cm=[3.0, 6.8, 6.8],
    )
    doc.p(
        "Both agents are `PromptAgentDefinition` agents created with `create_version()`. They are versioned, visible in the "
        "Foundry portal under Build → Agents, and reused by name from the orchestrator — created once, never re-created per run."
    )

    doc.h2("1.4 Tools, data sources and knowledge")
    doc.p(
        "The design principle is **tools are code, agents are prose**. Everything decidable by rules is decided in Python, "
        "and the agent only reasons over the structured result. This is the same `check_thresholds` pattern used in the "
        "course labs, applied to source code analysis."
    )
    doc.table(
        ["Component", "Type", "Used by", "Grounding role"],
        [
            ["`common/al_analysis.py`", "Deterministic parser", "`analyze_repo`, `get_repo_changes`", "Object types/ids/names, table fields, page actions, API properties, procedures, `[EventSubscriber]` attributes; classifies codeunits into three archetypes (logic → own section, subscribers → \"Övriga anpassningar\", install/upgrade → skipped); detects commented-out bodies"],
            ["GitHub REST API", "Data source (read-only PAT)", "both tools, discovery", "Source of truth for code, tree, compare, merged pull requests"],
            ["Business Central Automation API", "Data source (client credentials via GDAP)", "`discover_bc_extensions.py`", "Installed extensions and versions per environment"],
            ["`discovery/repos_config.json`", "Inventory", "discovery, orchestrator", "Which repos belong to which customer; app id/name/version; head SHA"],
            ["`output/{Kund}/.doc_state.json`", "State", "orchestrator", "Last documented SHA and version per repo → incremental runs"],
            ["`known_extensions.json`", "Curated lookup (optional)", "BC report", "Descriptions and vendor links for third-party ISV apps"],
            ["`agents/instructions/*.md`", "Governance", "agents", "Format standard derived from the partner's reference document; versioned in git"],
        ],
        widths_cm=[4.0, 3.0, 3.0, 6.6],
    )
    doc.p(
        "There is deliberately **no vector store or retrieval-augmented generation in version 1**. The ground truth is "
        "always the current code, which fits in the model's context per repository. A knowledge base of past documents "
        "would risk describing removed features. A curated knowledge base for process descriptions (Section 2 of the "
        "partner's template, *Flödesbeskrivning*) is a planned extension, see Section 3.4.",
    )

    doc.h2("1.5 Why a multi-agent approach")
    doc.bullets(
        [
            "**Different questions on different data.** The tracker reasons about a small diff and must be precise about deltas; the analyst reasons about a whole repository and must be complete. One prompt asked to be both surgical and exhaustive degrades at both.",
            "**Cost and latency.** The orchestrator skips unchanged repositories with a SHA comparison (zero LLM cost), runs the cheap tracker on changed ones, and regenerates fully only on `major` impact. A single-agent design would re-read every repository every night.",
            "**Separately measurable.** Verdict accuracy (is `impact` correct?) and documentation quality (grounded, Swedish, well-structured?) are evaluated with different cases and metrics, so regressions are attributable to one agent.",
            "**A second deliverable for free.** The tracker's changelog *is* the customer-facing release note (*Ändringshistorik*).",
            "**Independent evolution.** The tracker can later gain a Jira or Azure DevOps tool; the analyst can gain a terminology glossary — without touching the other agent's instructions or evaluation set.",
        ],
        numbered=True,
    )

    doc.h2("1.6 Information flow between the agents")
    doc.figure("sequence", "Figure 3 — Sequence per repository: SHA check, change tracker, verdict-driven analyst mode, deterministic assembly.", width_cm=15.5)
    doc.bullets(
        [
            "The orchestrator compares the repository's head SHA with the SHA stored in `.doc_state.json`.",
            "If it changed, `bc-change-tracker` calls `get_repo_changes(base_sha, head_sha)` and returns a JSON verdict and a Swedish changelog entry.",
            "The verdict decides the analyst's mode. In **update** mode the analyst receives the current section and the change summary, calls `analyze_repo` for the current code, and returns the full updated section while keeping unchanged paragraphs — the customer's documentation diff stays small.",
            "The orchestrator assembles the document deterministically: metadata header, the agent's `###` section between marker comments, and the *Ändringshistorik* with the tracker's entry prepended.",
            "The customer index cross-references the BC environment reports from discovery, so one page shows documented version, version in Git and version in each BC environment.",
        ],
        numbered=True,
    )

    # =============================================================================================
    doc.page_break()
    doc.h1("2. Production-readiness plan")
    doc.h2("2.1 Observability strategy")
    doc.figure("monitoring", "Figure 4 — Span hierarchy exported through OpenTelemetry to Application Insights; the Foundry portal reads the same data.", width_cm=13.5)
    doc.h3("Traces collected")
    doc.table(
        ["Span", "Attributes", "Question it answers"],
        [
            ["GenAI spans (automatic, `AIProjectInstrumentor`)", "model, input/output tokens, latency, prompt and completion content, tool call name/arguments/result, content-filter results", "Is the model slow or failing? What did the agent actually see and say? Did GitHub time out inside the tool?"],
            ["`bc.pipeline.run`", "`bc.repos`, `bc.documented`, `bc.updated`, `bc.skipped`, `bc.failed`, `bc.tokens_in/out`, `bc.duration_s`", "Did tonight's run succeed? Alert on `bc.failed > 0`"],
            ["`bc.pipeline.customer`", "`bc.customer`, `bc.repos`, `bc.failed`", "Per-customer roll-up"],
            ["`bc.pipeline.repo`", "`bc.repo`, `bc.mode` (full/update/skip/no_app), `bc.impact`, `bc.pull_requests`, `bc.tokens_*`, `bc.duration_s`, `bc.section_chars`", "Cost per repository, mode distribution, slow repositories"],
            ["`bc.agent.change_tracker` / `bc.agent.code_analyst`", "`bc.repo`, `bc.mode`", "Attribute latency and tokens to the right agent"],
        ],
        widths_cm=[4.2, 6.6, 5.8],
    )
    doc.h3("Monitoring metrics")
    doc.p("Eight ready-made Kusto queries ship in `monitoring/queries.kql`, all keyed on the `bc.*` custom dimensions:")
    doc.bullets(
        [
            "Pipeline runs over time with documented / updated / skipped / failed counts",
            "Token cost per customer (last 30 days) — which customers drive the LLM bill",
            "Mode distribution per day — how effective the SHA-based change detection is",
            "Impact verdict distribution per repository — are pull requests mostly minor or major",
            "Slowest repositories — candidates for a larger source budget or a repository split",
            "Per-agent GenAI statistics: runs, errors, p50/p95 latency, tokens",
            "Tool call health: `analyze_repo` and `get_repo_changes` failures and duration",
            "Failure alert — any run in the last day with `bc.failed > 0`",
        ]
    )
    doc.h3("How the insights are used")
    doc.table(
        ["Symptom", "Where to look", "Action"],
        [
            ["A consultant reports a documented feature that does not exist", "Latest `bc.pipeline.repo` trace → `analyze_repo` span", "If the object is absent from the tool output the model hallucinated → tighten instructions, add an evaluation case. If present but misdescribed the source was truncated (`source_omitted_for_budget`) → raise `MAX_AL_CHARS` or split the repository"],
            ["Rising `update`/`full` ratio", "Mode distribution query", "Developers merge often; consider a PR-triggered run instead of nightly"],
            ["Tokens per repository trending up", "Cost per customer query, `bc.section_chars`", "Repositories are growing; review source budget, consider per-folder documentation"],
            ["p95 latency spikes", "Per-agent GenAI query", "Model deployment capacity (TPM) or GitHub API rate limits"],
            ["`bc.failed > 0`", "Failure alert query → run trace", "Exception text is on the span; per-repo isolation means the rest of the run completed"],
        ],
        widths_cm=[4.4, 4.6, 7.6],
    )
    doc.p(
        "Message-content capture (`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`) stores prompts and completions, "
        "which include customer AL source. That is what makes debugging possible, so the Application Insights resource is "
        "treated as customer-confidential: dedicated resource group, restricted readers, default 90-day retention.",
        italic=True,
    )

    doc.h2("2.2 Evaluation strategy")
    doc.figure("evaluation", "Figure 5 — Evaluation flow: dataset → agents → LLM judge and deterministic evaluators → results and quality gate.", width_cm=16.6)
    doc.h3("Why evaluate a documentation generator")
    doc.p(
        "Monitoring tells you the pipeline ran. Evaluation tells you whether a consultant can trust the output. The failure "
        "modes specific to this solution are: **hallucinated features** (a fluent Swedish paragraph about a setup page that "
        "does not exist), **format drift** (a model update starts emitting bullet lists, English, or a changelog inside the "
        "section), **wrong impact verdicts** (a new codeunit rated `minor`, so the pipeline patches instead of regenerating) "
        "and **skipped archetype rules** (install codeunits documented, subscribers not collapsed)."
    )
    doc.h3("Dataset")
    doc.p(
        "`evaluation/evaluation_dataset.json` contains nine cases for a fictional customer, *Nordvik Industri AB*. Each case "
        "carries the exact tool output the agent would have received (the analysis JSON or the change JSON), so evaluation "
        "runs without GitHub access and is fully reproducible. Each `expected` block holds `must_mention` facts, "
        "`required_headings`, `forbidden` phrases, the expected impact, and a Swedish reference answer used as ground truth "
        "in the Foundry portal."
    )
    doc.table(
        ["Case", "Agent", "What it tests"],
        [
            ["CA-01", "code_analyst", "Logic codeunit + setup table/page + release trigger → its own `####` section"],
            ["CA-02", "code_analyst", "Subscriber-only codeunit plus install codeunit → \"Övriga anpassningar\", install skipped"],
            ["CA-03", "code_analyst", "Commented-out codeunit → \"Fungerar ej då logiken ej är implementerad\""],
            ["CA-04", "code_analyst", "Processing-only report triggered from a page action"],
            ["CA-05", "code_analyst", "API page properties, table extension, setup page, dependency"],
            ["CA-06", "code_analyst", "Update mode: integrate a new feature, keep unchanged text, no changelog in the section"],
            ["CT-01", "change_tracker", "Minor change via one pull request → `minor`, no full regeneration"],
            ["CT-02", "change_tracker", "New codeunit and new dependency → `major`, full regeneration"],
            ["CT-03", "change_tracker", "Version bump and pipeline files only → `none`"],
        ],
        widths_cm=[1.8, 3.0, 11.8],
    )
    doc.h3("Criteria")
    doc.table(
        ["Metric", "Type", "Why it matters here"],
        [
            ["Groundedness", "LLM judge (context = tool JSON)", "The number-one risk: fluent invention of features"],
            ["Task adherence", "LLM judge", "Did the agent follow the archetype and format instructions?"],
            ["Coherence", "LLM judge", "One feature per section, no contradictions"],
            ["Fluency", "LLM judge", "Professional Swedish"],
            ["Format adherence", "Deterministic", "`###`/`####` structure, forbidden phrases, JSON verdict block, Swedish markers — runs free in CI"],
            ["Coverage", "Deterministic", "Share of required facts (fields, actions, PR numbers) present"],
            ["Verdict accuracy", "Deterministic", "`impact` and `requires_full_regeneration` match expectations"],
        ],
        widths_cm=[3.4, 4.2, 9.0],
    )
    doc.p(
        "Tool Call Accuracy is intentionally not used in the portal because local FunctionTools cannot execute there; tool "
        "usage is instead verified through the traces (Section 2.1) and by the fact that the deterministic checks cannot pass "
        "without the tool's data. The judge uses the same gpt-5.4 deployment through the Foundry account endpoint with "
        "Entra ID authentication."
    )
    doc.h3("Integration into the development lifecycle")
    doc.bullets(
        [
            "**Pre-merge.** GitHub Actions runs the deterministic evaluators (`evaluate.py --offline --no-llm-judge`) on every pull request. Pull requests touching `agents/instructions/` or `common/al_analysis.py` additionally run the full LLM-judged evaluation with a 3.5 threshold gate; the job exits non-zero when any metric mean is below it.",
            "**Pre-release.** `agents.py --recreate` publishes a new agent version only after the gate passes. Old versions stay in Foundry for rollback.",
            "**In production.** Weekly scheduled portal evaluation on the agents' traces (Foundry → Agent → Monitor → Scheduled evaluations); quality trends next to cost and latency.",
            "**Feedback loop.** A consultant flags a document → the repository's analysis becomes a new case → fix → re-evaluate. The dataset grows with the product; the portal can also convert production traces into datasets.",
        ],
        numbered=True,
    )
    doc.p("The deterministic gate already runs green on the reference answers:", size=10)
    doc.code(
        "$ python evaluation/evaluate.py --offline --no-llm-judge\n"
        "[CA-01] Logic codeunit with setup table/page and release trigger   format_adherence=5.0, coverage=5.0\n"
        "[CA-02] Subscriber-only codeunit plus install codeunit             format_adherence=5.0, coverage=5.0\n"
        "...\n"
        "[CT-03] No functional change: version bump and pipeline files only format_adherence=5.0, coverage=5.0\n"
        "  format_adherence     5.0\n"
        "  coverage             5.0\n"
        "  Quality gate (>= 3.5): PASSED"
    )

    doc.h2("2.3 Governance and reliability")
    doc.h3("Consistent outputs")
    doc.bullets(
        [
            "The **format** is enforced by instruction files versioned in git and verified by deterministic evaluators on every pull request.",
            "The **content** is bounded by tool output: the analyst cannot document an object that `analyze_repo` did not find.",
            "The orchestrator assembles the final document itself — header, section between marker comments, change history — so agents never touch metadata or history, and manual notes outside the markers survive regeneration.",
            "An agent response that does not start with a `###` heading is rejected; an existing document is never overwritten with a malformed one.",
        ]
    )
    doc.h3("Grounding through knowledge sources and tools")
    doc.p(
        "Archetype classification (which files become sections, which are collapsed, which are skipped), field and action "
        "extraction, event-subscriber parsing, and the Git-versus-Business-Central version validation are all code, not model "
        "judgement. The model receives verified facts and phrases them; the instruction files tell it explicitly to say when "
        "source was omitted for size rather than guess. Pull request titles and bodies give the tracker the *why* behind a "
        "change without inventing intent."
    )
    doc.h3("Safe behaviour")
    doc.bullets(
        [
            "Foundry content filters are active on both agents (default Responsible AI configuration).",
            "The pipeline only **reads** GitHub and Business Central and only **writes** Markdown into its own repository; there are no write actions against customer systems.",
            "A human still reviews documents before they are handed to customers; the tool is decision support for consultants, not an autonomous publisher to customers.",
            "Traces containing customer code live in a dedicated, access-restricted Application Insights resource.",
        ]
    )
    doc.h3("Maintainability and least privilege")
    doc.table(
        ["Concern", "Measure"],
        [
            ["Structure", "Six folders mirror the lifecycle: `setup`, `discovery`, `agents`, `monitoring`, `evaluation`, `orchestration`; shared code in `common`"],
            ["Configuration", "Credentials read as environment variable → JSON file fallback; same code runs locally with `.env` and unattended in GitHub Actions"],
            ["Prompts", "Markdown instruction files, reviewable by consultants, versioned in git, published as immutable agent versions"],
            ["Idempotency", "`.doc_state.json` makes every run resumable; a second run right after the first costs zero tokens"],
            ["Failure handling", "Per-repository try/except with continue; failures counted, printed, traced; exit code 1 for the scheduler"],
            ["GitHub access", "Dedicated bot account, fine-grained PAT with Contents / Metadata / Pull requests read-only"],
            ["Business Central access", "One app registration in the partner tenant using GDAP delegated administration; customer tenant id per environment; no per-customer secrets"],
            ["Foundry access", "Entra ID (`DefaultAzureCredential`) everywhere, no API keys; GitHub Actions authenticates with OIDC"],
            ["Infrastructure", "Dedicated resource group created by `setup/deploy.sh`; `cleanup.sh` removes it"],
        ],
        widths_cm=[3.6, 13.0],
    )

    # =============================================================================================
    doc.page_break()
    doc.h1("3. End-to-end workflow")
    doc.h2("3.1 Sequence of agent interactions")
    doc.figure("orchestration", "Figure 6 — The production pipeline (`orchestration/run_pipeline.py`): SHA-based change detection routes each repository to skip, update or full regeneration.", width_cm=8.2)
    doc.bullets(
        [
            "**Trigger** — nightly GitHub Actions schedule (or manual dispatch; a pull-request-merge webhook is the planned next step).",
            "**Discovery** — `discover_repos.py` refreshes the customer inventory with `app.json` metadata and head SHAs; `discover_bc_extensions.py` queries each Business Central environment and writes the *Installerade tillägg* report with version validation.",
            "**Change detection** — per repository, head SHA versus `.doc_state.json`.",
            "**bc-change-tracker** — `get_repo_changes` → verdict + Swedish changelog.",
            "**bc-code-analyst** — `analyze_repo` → full or updated *Anpassningar* section.",
            "**Assembly** — one document per app, change history prepended, customer index regenerated with Git-versus-BC versions.",
            "**Publish** — commit to the documentation repository → Microsoft 365 Copilot GitHub connector indexes → consultants ask Copilot.",
            "**Observe, evaluate, improve** — traces and KPIs in Application Insights; scheduled evaluations; dataset grows from feedback.",
        ],
        numbered=True,
    )

    doc.h2("3.2 Information passed between steps")
    doc.table(
        ["From → To", "Payload"],
        [
            ["Discovery → orchestrator", "`repos_config.json` (repositories, app id/name/version, head SHA); BC reports (versions, statuses per environment)"],
            ["Orchestrator → bc-change-tracker", "`org`, `repo`, `base_sha`, `head_sha`"],
            ["bc-change-tracker → GitHub (tool)", "compare API, merged pull requests, patches for `.al` and `app.json`, changed-object classification"],
            ["bc-change-tracker → orchestrator", "Verdict JSON (`impact`, `affected_features`, `new_objects`, `requires_full_regeneration`, `pull_requests`, `summary_sv`) + changelog Markdown"],
            ["Orchestrator → bc-code-analyst", "Mode; `org/repo/branch`; in update mode also the current section and the verdict/changelog"],
            ["bc-code-analyst → GitHub (tool)", "Tree, `app.json`, all `.al` files → structured analysis with archetypes and source under a size budget"],
            ["bc-code-analyst → orchestrator", "`###` section (Swedish)"],
            ["Orchestrator → files", "`{Kund}_{repo}.md`, `.doc_state.json`, customer `README.md`"],
            ["Files → Copilot", "Markdown indexed by the GitHub connector"],
        ],
        widths_cm=[5.0, 11.6],
    )

    doc.h2("3.3 Discovery and version validation")
    doc.figure("discovery", "Figure 7 — Discovery is deterministic and isolated: the BC script reads the inventory and writes its own per-environment report.", width_cm=16.6)
    doc.p(
        "The Business Central script replaces the proof of concept's manual placeholder (\"KRÄVER MANUELL KOMPLETTERING\") "
        "with a deterministic validation. Own-published apps are matched to repositories by app id first, then by "
        "normalised name, and compared on major.minor.build:"
    )
    doc.table(
        ["Status", "Meaning"],
        [
            ["✅ Matchar", "`app.json` version equals the published version"],
            ["⚠️ Git är nyare – ej publicerad ändring", "Source has moved on; the environment runs an older build"],
            ["⚠️ BC är nyare – källkod saknar publicerad version", "A build is installed that is not in the default branch (hotfix branch, unpushed change)"],
            ["❓ Inget repo hittades", "Own-published app without a matching repository — renamed or unpublished"],
            ["❔ Ej publicerad i miljön", "Repository with `app.json` that is not installed in this environment"],
        ],
        widths_cm=[6.4, 10.2],
    )

    doc.h2("3.4 Final output delivered to the business")
    doc.p("Per customer the pipeline maintains a folder that reads like the partner's hand-written implementation document, but never goes stale:")
    doc.code(
        "output/\n"
        "└── Nordvik_Industri_AB/\n"
        "    ├── README.md                                  # index: apps, versions Git vs BC, links, latest changes\n"
        "    ├── Nordvik_Industri_AB_Nordvik-PTE.md         # Anpassningar + Ändringshistorik for one app\n"
        "    ├── Nordvik_Industri_AB_Nordvik-API-PTE.md\n"
        "    ├── Nordvik_Industri_AB_bc_Production.md       # installed extensions + version validation\n"
        "    ├── Nordvik_Industri_AB_bc_Production.json\n"
        "    └── .doc_state.json                            # last documented SHA / version / cost per repo"
    )
    doc.p("Excerpt of a generated app document (fictional customer, from the evaluation dataset):", size=10)
    doc.code(
        "### Nordvik PTE\n"
        "Kundspecifika anpassningar för Nordvik Industri AB. Appen är beroende av SweBase ...\n"
        "\n"
        "#### Minimumorderavgift (NVK Calc Minimum Order Fee)\n"
        "Funktionen lägger automatiskt till en avgiftsrad på försäljningsorder vars artikelsumma understiger\n"
        "ett konfigurerat minimibelopp. Inställningarna görs på sidan NVK Min. Order Fee Setup ... När en order\n"
        "frisläpps (Release Sales Document, OnAfterReleaseSalesDoc) beräknas summan av orderns artikelrader ...\n"
        "\n"
        "#### Kreditlimitkontroll (NVK Custom Credit Limit Mgt.)\n"
        "Kundkortet har utökats med fältet NVK Custom Credit Limit ... överstiger summan den egna kreditlimiten\n"
        "stoppas frisläppningen med ett felmeddelande.\n"
        "\n"
        "#### Övriga anpassningar\n"
        "- **Externt dokumentnummer från kund** – ... (`SetExternalDocNoFromCustomer`)\n"
        "\n"
        "## Ändringshistorik\n"
        "#### 2026-09-10 – version 27.2.0.0 → 27.3.0.0\n"
        "**Nya funktioner**\n"
        "- Kreditlimitkontroll: Ny codeunit NVK Custom Credit Limit Mgt. stoppar frisläppning ... (PR #51)"
    )
    doc.p(
        "Consultants consume this through Copilot chat, for example: *\"Vilka anpassningar har Nordvik på inköpsorder och "
        "när ändrades de senast?\"* — the answer cites the app document and its change history."
    )

    doc.h2("3.5 Deployment, monitoring, evaluation and improvement over time")
    doc.figure("setup", "Figure 8 — Infrastructure provisioned by `setup/deploy.sh` in a dedicated resource group.", width_cm=16.6)
    doc.table(
        ["Aspect", "Version 1 (this repository)", "Next iteration"],
        [
            ["Deployment", "GitHub Actions nightly (`generate-docs.yml`), Azure OIDC login, secrets in GitHub; commits `output/` for the Copilot connector", "Pull-request-merge webhook → Azure Function documenting just that repository within minutes"],
            ["Monitoring", "Application Insights traces, `bc.*` KPIs, KQL queries, failure alert", "Azure Monitor workbook per customer; budget alert on tokens"],
            ["Evaluation", "Nine-case dataset, LLM judge + deterministic gate, portal evaluations", "Dataset built from production traces; consultant thumbs-up/down feeding new cases"],
            ["Documentation scope", "Section 3 *Anpassningar* + Section 1 extension inventory with version validation", "Section 2 *Flödesbeskrivning* from a curated knowledge base (File Search); internal/shared repositories"],
            ["Agents", "Two", "Optional reviewer agent scoring each section before publish; Jira/DevOps tool for the tracker"],
            ["Orchestration", "Python orchestrator (function-call loops); Foundry Workflow agent for portal visibility", "Foundry Workflow as primary once hosted tools can call GitHub"],
        ],
        widths_cm=[3.0, 7.0, 6.6],
    )

    # =============================================================================================
    doc.page_break()
    doc.h1("4. From prototype to production — reflection")
    doc.p(
        "The starting point was a working proof of concept: three Python scripts and one plain OpenAI Responses call per "
        "repository, with all AL files pasted into the prompt. It produced good Swedish documentation on the first real "
        "customer — and it had no way to tell whether the next run would too. The course concepts changed the design in "
        "five concrete ways:"
    )
    doc.table(
        ["Course concept", "Prototype", "Production architecture"],
        [
            ["Specialised agents with tools", "One prompt, all source pasted in", "Two `PromptAgentDefinition` agents, each with one deterministic FunctionTool; archetype rules moved from prompt text into code"],
            ["Knowledge sources and grounding", "Model inferred structure from raw AL", "Structured analysis JSON; the model cannot cite an object the tool did not find"],
            ["Tracing and monitoring", "Print statements", "OpenTelemetry GenAI spans + business KPIs per customer and repository in Application Insights"],
            ["Evaluation with datasets and metrics", "Read the output and judge by eye", "Reproducible dataset, four LLM-judge metrics plus deterministic evaluators, CI quality gate"],
            ["Orchestration into workflows", "Regenerate everything every run", "SHA-based incremental pipeline; tracker verdict routes to skip / update / full; Foundry Workflow agent for portal visibility"],
        ],
        widths_cm=[4.0, 4.4, 8.2],
    )
    doc.p(
        "The most valuable shift was treating *what the model is allowed to know* as an engineering artifact. Once the "
        "analysis tool decided which codeunits are business logic, which are event subscribers and which are install "
        "scaffolding, the agent's job became phrasing rather than judging — and phrasing is something the evaluators can "
        "measure. The second shift was accepting that a nightly pipeline is a cost problem: the change tracker exists as "
        "much to save tokens as to write release notes."
    )
    doc.p(
        "Status at submission: all phases are implemented and verified offline (module compilation, AL analyzer against the "
        "dataset, document renderers, deterministic evaluation gate). Live runs against Foundry, GitHub and Business Central "
        "require the partner's credentials and are the first operational step after provisioning with `setup/deploy.sh`.",
        italic=True,
    )

    doc.h1("Appendix A — Repository map")
    doc.table(
        ["Path", "Purpose"],
        [
            ["`README.md`, `SOLUTION_DESIGN.md`", "Overview with architecture diagram; the design in Markdown form"],
            ["`setup/deploy.sh`, `cleanup.sh`", "Provision / remove the dedicated resource group (Foundry account, project, gpt-5.4, Log Analytics, App Insights)"],
            ["`discovery/discover_repos.py`", "GitHub inventory with `app.json` metadata and head SHA"],
            ["`discovery/discover_bc_extensions.py`", "Business Central extension inventory and version validation report per environment"],
            ["`agents/agents.py`, `agents/tools.py`, `agents/instructions/*.md`", "The two agents, their FunctionTools and instruction files"],
            ["`common/al_analysis.py`, `common/github_client.py`, `common/tracing.py`, `common/config.py`", "Deterministic AL parser, GitHub client, OpenTelemetry helpers, configuration"],
            ["`monitoring/monitor.py`, `monitoring/queries.kql`", "Traced run and Kusto queries"],
            ["`evaluation/evaluate.py`, `evaluation/evaluation_dataset.json`, `evaluation/eval_portal.jsonl`", "Evaluation pipeline, dataset, portal export"],
            ["`orchestration/run_pipeline.py`, `orchestration/create_workflow_agent.py`", "Production pipeline; Foundry Workflow registration"],
            ["`.github/workflows/generate-docs.yml`", "Nightly scheduled run with OIDC login and commit-back"],
            ["`docs/examples/`", "Rendered sample output for a fictional customer"],
        ],
        widths_cm=[7.4, 9.2],
    )

    OUT_DOCX.parent.mkdir(parents=True, exist_ok=True)
    d.save(OUT_DOCX)
    return OUT_DOCX


def to_pdf(docx_path: Path) -> Path | None:
    try:
        from docx2pdf import convert

        pdf_path = docx_path.with_suffix(".pdf")
        convert(str(docx_path), str(pdf_path))
        return pdf_path if pdf_path.exists() else None
    except Exception as exc:  # Word not installed / COM unavailable
        print(f"[WARN] PDF export skipped: {exc}")
        return None


if __name__ == "__main__":
    out = build()
    print(f"[OK] {out}")
    if "--no-pdf" not in sys.argv:
        pdf = to_pdf(out)
        if pdf:
            print(f"[OK] {pdf}")
