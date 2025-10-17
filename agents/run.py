#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    # OpenAI Python SDK v1+
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - optional until user installs deps
    OpenAI = None  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_INDEX = REPO_ROOT / "docs" / "index.html"
STATE_FILE = REPO_ROOT / "agents" / "state.json"
REASONING_DIR = REPO_ROOT / "agent-reasoning"

BEGIN_MARKER = "<!-- BEGIN_EDITABLE -->"
END_MARKER = "<!-- END_EDITABLE -->"


def load_state() -> dict:
    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {"counter": 0}
    return {"counter": 0}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as f:
        return f.read()


def write_text(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(content)


def replace_editable_section(html: str, new_inner_html: str) -> str:
    # Replace content between BEGIN_EDITABLE and END_EDITABLE markers
    pattern = re.compile(
        re.escape(BEGIN_MARKER)
        + r"[\s\S]*?"
        + re.escape(END_MARKER),
        re.MULTILINE,
    )
    replacement = (
        BEGIN_MARKER
        + "\n      <section id=\"content\">\n"
        + new_inner_html
        + "\n      </section>\n      "
        + END_MARKER
    )
    if not pattern.search(html):
        raise RuntimeError(
            "Editable section markers not found in docs/index.html."
        )
    return pattern.sub(replacement, html)


def replace_last_updated_span(html: str, last_updated_text: str) -> str:
    # Replace the text content inside <span id="last-updated"> ... </span>
    def _repl(match: re.Match) -> str:
        prefix = match.group(1)
        suffix = match.group(2)
        return f"{prefix}{last_updated_text}{suffix}"

    pattern = re.compile(
        r"(id=\"last-updated\">)[^<]*(</span>)",
        re.MULTILINE,
    )
    if not pattern.search(html):
        # If the span doesn't exist, do nothing; page will fallback to its script
        return html
    return pattern.sub(_repl, html, count=1)


def extract_editable_inner(html: str) -> str:
    """Return the current inner HTML between the editable markers (without wrapper)."""
    pattern = re.compile(
        re.escape(BEGIN_MARKER) + r"([\s\S]*?)" + re.escape(END_MARKER), re.MULTILINE
    )
    m = pattern.search(html)
    if not m:
        return ""
    inner = m.group(1)
    # Optionally strip outer <section id="content"> if present
    inner = re.sub(r"^\s*<section[^>]*>\s*", "", inner)
    inner = re.sub(r"\s*</section>\s*$", "", inner)
    return inner.strip()


def now_strings() -> tuple[str, str]:
    now_utc = dt.datetime.now(dt.timezone.utc)
    est = ZoneInfo("America/New_York")
    now_est = now_utc.astimezone(est)
    # Human friendly and file-safe formats
    human_est = now_est.strftime("%Y-%m-%d %H:%M:%S EST")
    iso_z = now_utc.strftime("%Y-%m-%dT%H-%M-%SZ")
    return human_est, iso_z


def write_reasoning_log(
    *,
    mode: str,
    model: str,
    human_est: str,
    iso_z: str,
    dry_run: bool,
    applied_strategy: str,
    snippet_chars: int,
    validation_ok: bool,
    usage: dict | None,
    counter_value: int | None,
) -> Path:
    REASONING_DIR.mkdir(parents=True, exist_ok=True)
    log_path = REASONING_DIR / f"run-{iso_z}.md"
    prompt_path = REPO_ROOT / "agents" / "prompts" / "webmaster.md"
    prompt_text = ""
    if prompt_path.exists():
        prompt_text = read_text(prompt_path)
    log = []
    log.append(f"# Vibing Webmaster run — {human_est}")
    log.append("")
    log.append("## Task")
    log.append("")
    log.append("Incrementally beautify the editable section using only HTML/CSS; include a single span#last-updated.")
    log.append("")
    log.append("## Prompt (current)")
    log.append("")
    log.append("" if not prompt_text else prompt_text)
    log.append("")
    log.append("## Result")
    log.append("")
    log.append("- Applied: aesthetic snippet")
    log.append(f"- Snippet size: {snippet_chars} chars")
    if counter_value is not None:
        log.append(f"- Counter (for deterministic mode): {counter_value}")
    log.append("")
    log.append("## Meta")
    log.append("")
    log.append(f"- mode: {mode}")
    log.append(f"- model: {model}")
    log.append(f"- validation_ok: {validation_ok}")
    log.append(f"- strategy: {applied_strategy}")
    if usage is not None:
        # openai usage keys vary; print raw
        try:
            log.append(f"- usage: {json.dumps(usage)}")
        except Exception:
            log.append("- usage: (unavailable)")
    log.append(f"- dry_run: {dry_run}")
    log.append(f"- timestamp_est: {human_est}")
    log.append(f"- timestamp_utc: {iso_z}")
    write_text(log_path, "\n".join(log))
    return log_path


def load_prompt() -> str:
    prompt_path = REPO_ROOT / "agents" / "prompts" / "webmaster.md"
    return read_text(prompt_path) if prompt_path.exists() else ""


def call_llm_generate_content(model: str, system_prompt: str, user_prompt: str) -> tuple[str, dict | None]:
    if OpenAI is None:
        raise RuntimeError(
            "OpenAI SDK not installed. Run: pip install -r agents/requirements.txt"
        )
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set in environment")
    client = OpenAI()
    # Use Chat Completions for broad compatibility
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    text = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None)
    # usage may be pydantic model; try to coerce to dict
    usage_dict = None
    if usage is not None:
        try:
            usage_dict = usage.model_dump()  # type: ignore[attr-defined]
        except Exception:
            try:
                usage_dict = dict(usage)
            except Exception:
                usage_dict = None
    return text.strip(), usage_dict


def parse_counter_from_text(text: str) -> int | None:
    match = re.search(r"(-?\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


SAFE_BLOCKLIST = [
    # basic safety pass; not exhaustive, but avoid obvious inappropriate terms
    "porn", "nsfw", "nude", "racist", "sex", "violence", "gore",
]


def enforce_basic_safety(html_fragment: str) -> str:
    lowered = html_fragment.lower()
    for term in SAFE_BLOCKLIST:
        if term in lowered:
            raise RuntimeError(f"Generated content contained forbidden term: {term}")
    return html_fragment


FORBIDDEN_TAGS = ["link", "iframe", "object", "embed"]


def validate_fragment(fragment: str) -> str:
    # Disallow code fences and surrounding HTML/BODY/HEAD or DOCTYPE
    # Code fences should have been stripped earlier; if still present, treat as invalid
    if "```" in fragment:
        raise RuntimeError("Fragment must not contain markdown code fences.")
    lowered = fragment.lower()
    if any(tag in lowered for tag in ("<!doctype", "<html", "<head", "<body")):
        raise RuntimeError("Return only the inner HTML for the editable section, not a full page.")
    # Require exactly one last-updated span
    count_updated = len(re.findall(r"<span\s+id=\"last-updated\"[^>]*>", fragment, flags=re.IGNORECASE))
    if count_updated != 1:
        raise RuntimeError("Fragment must include exactly one <span id=\"last-updated\"></span>.")
    # Forbid dangerous tags
    for tag in FORBIDDEN_TAGS:
        if re.search(rf"<\s*{tag}[^>]*>", lowered):
            raise RuntimeError(f"Forbidden tag found: <{tag}>")
    return fragment


def strip_code_fences(text: str) -> str:
    """Remove surrounding markdown code fences if present and return inner content.
    Supports ```html ...``` or bare ``` ... ``` fences.
    """
    # Full fenced block from start to end
    m = re.match(r"^```[a-zA-Z0-9_-]*\s*\n([\s\S]*?)\n```\s*$", text.strip())
    if m:
        return m.group(1).strip()
    # Sometimes model adds fences only at start or end; strip them greedily
    text = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    return text.strip()


def run(mode: str, dry_run: bool, model: str) -> None:
    if not DOCS_INDEX.exists():
        print(f"Missing {DOCS_INDEX}. Create the site first.", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    prev_counter = int(state.get("counter", 0))
    iteration = int(state.get("iteration", 0)) + 1
    next_counter = prev_counter + 1

    human_est, iso_z = now_strings()

    usage_info: dict | None = None
    applied_strategy = ""
    validation_ok = False

    if mode == "llm":
        # Ask the model to incrementally beautify the current editable section using only HTML/CSS.
        current_inner = extract_editable_inner(read_text(DOCS_INDEX))
        system_prompt = load_prompt()
        user_prompt = (
            f"Iteration: {iteration}.\n"
            f"Here is the current editable inner HTML (between markers):\n---\n{current_inner}\n---\n"
        )
        try:
            candidate, usage_info = call_llm_generate_content(model=model, system_prompt=system_prompt, user_prompt=user_prompt)
            candidate = strip_code_fences(candidate.strip())
            candidate = enforce_basic_safety(candidate)
            candidate = validate_fragment(candidate)
            validation_ok = True
            applied_strategy = "llm"
            new_content = candidate
        except Exception as e:
            # Minimal tasteful fallback block when LLM fails
            new_content = (
                "<div style=\"padding:24px;border-radius:12px;background:rgba(255,255,255,0.05);"
                "border:1px solid rgba(255,255,255,0.12);\">"
                "<h2 style=\"margin:0 0 8px 0;\">A Small, Gentle Refresh</h2>"
                "<p style=\"margin:0 0 12px 0;opacity:0.85;\">Subtle textures, soft borders, and a calm palette.</p>"
                "<span id=\"last-updated\"></span>"
                "</div>"
            )
            applied_strategy = f"fallback ({e})"
            print(f"LLM error, used fallback aesthetic block: {e}")
    else:
        # Deterministic mode keeps a minimal aesthetic block with a counter for continuity
        new_content = (
            f"<div style=\"padding:16px;border-radius:12px;border:1px dashed rgba(255,255,255,0.25);\">"
            f"<div style=\"font-size:18px;margin-bottom:8px;\">Counter: {next_counter}</div>"
            f"<span id=\"last-updated\"></span>"
            f"</div>"
        )
        applied_strategy = "counter"
        validation_ok = True

    html = read_text(DOCS_INDEX)
    html = replace_editable_section(html, new_content)
    html = replace_last_updated_span(html, f"Last updated: {human_est}")

    # Persist state value chosen
    state["counter"] = next_counter
    state["iteration"] = iteration

    log_path = write_reasoning_log(
        mode=mode,
        model=model,
        human_est=human_est,
        iso_z=iso_z,
        dry_run=dry_run,
        applied_strategy=applied_strategy,
        snippet_chars=len(new_content),
        validation_ok=validation_ok,
        usage=usage_info,
        counter_value=state["counter"] if mode != "llm" else None,
    )

    if dry_run:
        print("Dry run complete. No files were modified.")
        print(f"Would have written reasoning log to: {log_path}")
        return

    # Persist changes
    save_state(state)
    write_text(DOCS_INDEX, html)
    print(f"Updated counter to {state['counter']} and wrote {DOCS_INDEX}")
    print(f"Reasoning log: {log_path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Vibing local agent runner")
    p.add_argument(
        "--mode",
        choices=["llm", "counter"],
        default="llm",
        help="Use OpenAI LLM ('llm') or deterministic counter ('counter')",
    )
    p.add_argument("--model", default=os.getenv("MODEL", "gpt-5"), help="OpenAI model name")
    p.add_argument("--dry-run", action="store_true", help="Compute without writing files")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(mode=args.mode, dry_run=args.dry_run, model=args.model)


