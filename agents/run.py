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

MAX_TOKENS_DEFAULT = int(os.getenv("MAX_TOKENS", "4096"))

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


def write_reasoning_log(counter_value: int, human_est: str, iso_z: str, dry_run: bool) -> Path:
    REASONING_DIR.mkdir(parents=True, exist_ok=True)
    log_path = REASONING_DIR / f"run-{iso_z}.md"
    prompt_path = REPO_ROOT / "agents" / "prompts" / "webmaster.md"
    prompt_text = ""
    if prompt_path.exists():
        prompt_text = read_text(prompt_path)
    log = []
    log.append(f"# Vibing run — {human_est}")
    log.append("")
    log.append("## Prompt")
    log.append("")
    log.append("" if not prompt_text else prompt_text)
    log.append("")
    log.append("## Output")
    log.append("")
    log.append(f"Counter incremented to {counter_value}.")
    log.append("")
    log.append("## Meta")
    log.append("")
    log.append(f"- dry_run: {dry_run}")
    log.append(f"- timestamp_est: {human_est}")
    log.append(f"- timestamp_utc: {iso_z}")
    write_text(log_path, "\n".join(log))
    return log_path


def load_prompt() -> str:
    prompt_path = REPO_ROOT / "agents" / "prompts" / "webmaster.md"
    return read_text(prompt_path) if prompt_path.exists() else ""


def call_llm_generate_content(model: str, system_prompt: str, user_prompt: str) -> str:
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
        temperature=0.2,
        max_tokens=MAX_TOKENS_DEFAULT,
    )
    text = resp.choices[0].message.content or ""
    return text.strip()


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


FORBIDDEN_TAGS = ["script", "link", "iframe", "object", "embed"]


def validate_fragment(fragment: str) -> str:
    # Disallow code fences and surrounding HTML/BODY/HEAD or DOCTYPE
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


def run(mode: str, dry_run: bool, model: str) -> None:
    if not DOCS_INDEX.exists():
        print(f"Missing {DOCS_INDEX}. Create the site first.", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    prev_counter = int(state.get("counter", 0))
    next_counter = prev_counter + 1

    human_est, iso_z = now_strings()
    prompt_text = load_prompt()

    if mode == "llm":
        # Ask the model to incrementally beautify the current editable section using only HTML/CSS.
        current_inner = extract_editable_inner(read_text(DOCS_INDEX))
        system_prompt = (
            "You are the Vibing Webmaster. Your job: improve the aesthetics of the"
            " editable section using ONLY inline HTML and CSS (no external libs)."
            " Preserve a <span id=\"last-updated\"></span> element somewhere in the"
            " returned markup so the system can fill it. Strictly avoid any"
            " inappropriate content."
        )
        user_prompt = (
            "Requirements:\n"
            "1) Use only HTML/CSS in the returned snippet; no JS or external libraries.\n"
            "2) Include a <span id=\"last-updated\"></span> element somewhere aesthetically integrated.\n"
            "3) Keep it self-contained; do not modify outside the editable section.\n"
            "4) Make incremental improvements; tasteful, accessible, and visually pleasing.\n"
            "5) Keep text appropriate; no profanity or sensitive content.\n\n"
            f"Here is the current editable inner HTML (between markers):\n---\n{current_inner}\n---\n"
            "Return ONLY the new inner HTML to replace the section, without surrounding comments."
        )
        try:
            candidate = call_llm_generate_content(model=model, system_prompt=system_prompt, user_prompt=user_prompt)
            candidate = candidate.strip()
            candidate = enforce_basic_safety(candidate)
            candidate = validate_fragment(candidate)
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
            print(f"LLM error, used fallback aesthetic block: {e}")
    else:
        # Deterministic mode keeps a minimal aesthetic block with a counter for continuity
        new_content = (
            f"<div style=\"padding:16px;border-radius:12px;border:1px dashed rgba(255,255,255,0.25);\">"
            f"<div style=\"font-size:18px;margin-bottom:8px;\">Counter: {next_counter}</div>"
            f"<span id=\"last-updated\"></span>"
            f"</div>"
        )

    html = read_text(DOCS_INDEX)
    html = replace_editable_section(html, new_content)
    html = replace_last_updated_span(html, f"Last updated: {human_est}")

    # Persist state value chosen
    state["counter"] = next_counter

    log_path = write_reasoning_log(state["counter"], human_est, iso_z, dry_run)

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
    p.add_argument("--model", default=os.getenv("MODEL", "gpt-4o"), help="OpenAI model name")
    p.add_argument("--dry-run", action="store_true", help="Compute without writing files")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(mode=args.mode, dry_run=args.dry_run, model=args.model)


