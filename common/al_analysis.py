"""
common/al_analysis.py — Deterministic analysis of Business Central AL source code.

This is the "grounding layer" of the solution: everything that can be decided by rules
(object types, codeunit archetypes, event subscribers, fields, dependencies) is decided
here in Python, and only the *structured result* is handed to the agent. The agent then
writes prose — it never has to guess what a file is.

Codeunit archetypes (from docs/06 in the original spec):
  1. logic            → its own H4 section in the documentation
  2. subscribers      → collapsed into a single "Övriga anpassningar" H4 section
  3. install_upgrade  → skipped entirely (no business logic)
"""

from __future__ import annotations

import json
import re
from collections import Counter

OBJECT_TYPES = (
    "codeunit", "table", "tableextension", "page", "pageextension", "report", "reportextension",
    "enum", "enumextension", "query", "xmlport", "permissionset", "permissionsetextension",
    "interface", "controladdin", "entitlement", "profile", "pagecustomization", "dotnet",
)

_OBJECT_RE = re.compile(
    r"^\s*(" + "|".join(OBJECT_TYPES) + r")\s+(\d+)?\s*(\"(?P<qname>[^\"]+)\"|(?P<name>[A-Za-z_][\w]*))"
    r"(?:\s+extends\s+(\"(?P<qext>[^\"]+)\"|(?P<ext>[A-Za-z_][\w]*)))?",
    re.IGNORECASE | re.MULTILINE,
)
_SUBTYPE_RE = re.compile(r"\bSubtype\s*=\s*(Install|Upgrade|Test|TestRunner)\s*;", re.IGNORECASE)
_PROC_RE = re.compile(
    r"^\s*(?P<mods>(?:(?:local|internal|protected)\s+)?)(?:procedure|trigger)\s+(?P<name>[\w\"]+)\s*\(",
    re.IGNORECASE | re.MULTILINE,
)
_SUBSCRIBER_RE = re.compile(
    r"\[EventSubscriber\(\s*ObjectType::(?P<otype>\w+)\s*,\s*(?:\w+::)?(?P<oname>\"[^\"]+\"|\w+)\s*,"
    r"\s*'?(?P<event>[^,'\)]+)'?\s*(?:,\s*'?(?P<element>[^,'\)]*)'?)?[^\]]*\]\s*"
    r"(?:local\s+|internal\s+)?procedure\s+(?P<proc>[\w\"]+)",
    re.IGNORECASE | re.DOTALL,
)
_FIELD_RE = re.compile(
    r"^\s*field\(\s*(?P<id>\d+)\s*;\s*(?P<name>\"[^\"]+\"|\w+)\s*;\s*(?P<type>[^\)\n]+?)\s*\)",
    re.IGNORECASE | re.MULTILINE,
)
_ACTION_RE = re.compile(r"^\s*action\(\s*(?P<name>\"[^\"]+\"|\w+)\s*\)", re.IGNORECASE | re.MULTILINE)
_CAPTION_RE = re.compile(r"\bCaption\s*=\s*'(?P<caption>[^']*)'", re.IGNORECASE)
_PAGETYPE_RE = re.compile(r"\bPageType\s*=\s*(\w+)\s*;", re.IGNORECASE)
_SOURCETABLE_RE = re.compile(r"\bSourceTable\s*=\s*(\"[^\"]+\"|\w+)\s*;", re.IGNORECASE)
_APIPROPS_RE = re.compile(r"\b(APIPublisher|APIGroup|APIVersion|EntityName|EntitySetName)\s*=\s*'([^']*)'", re.IGNORECASE)
_PROCESSING_ONLY_RE = re.compile(r"\bProcessingOnly\s*=\s*true", re.IGNORECASE)


def strip_comments(source: str) -> str:
    """Remove // line comments and /* */ block comments (keeps line structure)."""
    no_block = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", no_block)


def _unquote(name: str | None) -> str:
    if name is None:
        return ""
    return name.strip().strip('"')


def parse_object_header(source: str) -> dict | None:
    m = _OBJECT_RE.search(source)
    if not m:
        return None
    return {
        "type": m.group(1).lower(),
        "id": int(m.group(2)) if m.group(2) else None,
        "name": m.group("qname") or m.group("name") or "",
        "extends": m.group("qext") or m.group("ext") or None,
    }


def is_body_commented_out(source: str) -> bool:
    """True when the object declaration exists but nearly all code lines are comments."""
    lines = [ln.strip() for ln in source.splitlines() if ln.strip()]
    if len(lines) < 4:
        return False
    code_lines = [ln for ln in strip_comments(source).splitlines() if ln.strip()]
    meaningful = [ln for ln in code_lines if ln.strip() not in ("{", "}")]
    # header + maybe a few property lines only
    return len(meaningful) <= 3 and len(lines) > 8


def extract_procedures(stripped: str) -> list[dict]:
    procs = []
    for m in _PROC_RE.finditer(stripped):
        mods = m.group("mods").lower()
        name = _unquote(m.group("name"))
        is_trigger = bool(re.match(r"^\s*(?:local\s+)?trigger", m.group(0), re.IGNORECASE))
        procs.append({"name": name, "public": not mods.strip() and not is_trigger, "trigger": is_trigger})
    return procs


def extract_event_subscribers(stripped: str) -> list[dict]:
    subs = []
    for m in _SUBSCRIBER_RE.finditer(stripped):
        subs.append(
            {
                "object_type": m.group("otype"),
                "object_name": _unquote(m.group("oname")),
                "event": m.group("event").strip(),
                "element": (m.group("element") or "").strip() or None,
                "procedure": _unquote(m.group("proc")),
            }
        )
    return subs


def classify_codeunit(path: str, stripped: str, subscribers: list[dict], procedures: list[dict]) -> str:
    """Archetype 3 (install/upgrade) → 2 (subscribers) → 1 (logic)."""
    sub = _SUBTYPE_RE.search(stripped)
    if sub and sub.group(1).lower() in ("install", "upgrade"):
        return "install_upgrade"
    if sub and sub.group(1).lower() in ("test", "testrunner"):
        return "test"
    filename = path.rsplit("/", 1)[-1].lower()
    public_procs = [p for p in procedures if p["public"]]
    if "subscriber" in filename or (subscribers and not public_procs):
        return "subscribers"
    return "logic"


def analyze_file(path: str, source: str) -> dict:
    stripped = strip_comments(source)
    header = parse_object_header(stripped) or parse_object_header(source)
    info: dict = {
        "path": path,
        "type": header["type"] if header else "unknown",
        "id": header["id"] if header else None,
        "name": header["name"] if header else path.rsplit("/", 1)[-1],
        "extends": header["extends"] if header else None,
        "chars": len(source),
        "commented_out": is_body_commented_out(source),
    }
    caption = _CAPTION_RE.search(stripped)
    if caption:
        info["caption"] = caption.group("caption")

    if info["type"] == "codeunit":
        procedures = extract_procedures(stripped)
        subscribers = extract_event_subscribers(stripped)
        info["procedures"] = procedures
        info["event_subscribers"] = subscribers
        info["archetype"] = classify_codeunit(path, stripped, subscribers, procedures)
    elif info["type"] in ("table", "tableextension"):
        info["fields"] = [
            {"id": int(m.group("id")), "name": _unquote(m.group("name")), "type": m.group("type").strip()}
            for m in _FIELD_RE.finditer(stripped)
        ]
        info["procedures"] = extract_procedures(stripped)
    elif info["type"] in ("page", "pageextension"):
        pt = _PAGETYPE_RE.search(stripped)
        st = _SOURCETABLE_RE.search(stripped)
        info["page_type"] = pt.group(1) if pt else None
        info["source_table"] = _unquote(st.group(1)) if st else None
        info["actions"] = [_unquote(m.group("name")) for m in _ACTION_RE.finditer(stripped)]
        api = {k.lower(): v for k, v in _APIPROPS_RE.findall(stripped)}
        if api:
            info["api"] = api
        info["procedures"] = extract_procedures(stripped)
    elif info["type"] in ("report", "reportextension"):
        info["processing_only"] = bool(_PROCESSING_ONLY_RE.search(stripped))
        info["procedures"] = extract_procedures(stripped)
    return info


def _source_block(path: str, source: str) -> str:
    return f"--- {path} ---\n{source.strip()}\n"


def analyze_repo_files(app_json: dict, al_files: dict[str, str], max_chars: int) -> dict:
    """
    Build the structured analysis handed to the Code Analyst agent.

    `al_files` maps repo path → source text. Source is included under a character budget,
    prioritised so the model always sees business logic first:
      logic codeunits → subscriber codeunits → tables/extensions → pages/extensions → reports → rest.
    Install/upgrade codeunits are listed as skipped and their source is never sent.
    """
    files = [analyze_file(path, src) for path, src in sorted(al_files.items())]
    by_type = Counter(f["type"] for f in files)

    logic = [f for f in files if f["type"] == "codeunit" and f.get("archetype") == "logic"]
    subscribers = [f for f in files if f["type"] == "codeunit" and f.get("archetype") == "subscribers"]
    skipped = [f for f in files if f["type"] == "codeunit" and f.get("archetype") in ("install_upgrade", "test")]
    tables = [f for f in files if f["type"] in ("table", "tableextension")]
    pages = [f for f in files if f["type"] in ("page", "pageextension")]
    reports = [f for f in files if f["type"] in ("report", "reportextension")]
    other = [f for f in files if f not in logic + subscribers + skipped + tables + pages + reports]

    # Source budget
    budget = max_chars
    included: list[str] = []
    omitted: list[str] = []
    for group in (logic, subscribers, tables, pages, reports, other):
        for f in group:
            src = al_files[f["path"]]
            block = _source_block(f["path"], src)
            if len(block) <= budget:
                included.append(block)
                budget -= len(block)
                f["source_included"] = True
            else:
                omitted.append(f["path"])
                f["source_included"] = False

    def compact(f: dict) -> dict:
        keep = {k: v for k, v in f.items() if k not in ("chars",)}
        return keep

    deps = [
        {"name": d.get("name"), "publisher": d.get("publisher"), "version": d.get("version")}
        for d in app_json.get("dependencies", [])
    ]
    return {
        "app": {
            "id": app_json.get("id"),
            "name": app_json.get("name"),
            "publisher": app_json.get("publisher"),
            "version": app_json.get("version"),
            "brief": app_json.get("brief"),
            "description": app_json.get("description"),
            "application": app_json.get("application"),
            "runtime": app_json.get("runtime"),
            "dependencies": deps,
        },
        "summary": {
            "al_files": len(files),
            "objects_by_type": dict(by_type),
            "logic_codeunits": len(logic),
            "subscriber_codeunits": len(subscribers),
            "event_subscribers": sum(len(f.get("event_subscribers", [])) for f in subscribers + logic),
            "skipped_install_upgrade": [f["name"] for f in skipped],
            "source_omitted_for_budget": omitted,
        },
        "logic_codeunits": [compact(f) for f in logic],
        "subscriber_codeunits": [compact(f) for f in subscribers],
        "tables": [compact(f) for f in tables],
        "pages": [compact(f) for f in pages],
        "reports": [compact(f) for f in reports],
        "other_objects": [compact(f) for f in other],
        "source": "\n".join(included),
    }


def analysis_to_json(analysis: dict) -> str:
    return json.dumps(analysis, ensure_ascii=False, indent=2)


def normalize_version(version: str | None, parts: int = 3) -> tuple[str, ...]:
    """Compare on major.minor.build — app.json carries 4 parts, BC reports 3."""
    if not version:
        return ()
    return tuple(version.strip().split(".")[:parts])


def compare_versions(git_version: str | None, bc_version: str | None) -> str:
    """'match' | 'git_ahead' | 'bc_ahead' | 'unknown'."""
    g, b = normalize_version(git_version), normalize_version(bc_version)
    if not g or not b:
        return "unknown"
    if g == b:
        return "match"

    def as_ints(t):
        out = []
        for x in t:
            try:
                out.append(int(x))
            except ValueError:
                out.append(0)
        return out

    return "git_ahead" if as_ints(g) > as_ints(b) else "bc_ahead"
