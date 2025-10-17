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
        + "\n      <section id=\"content\">\n        "
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
        max_tokens=64,
    )
    text = resp.choices[0].message.content or ""
    # Normalize to single line plain text
    return " ".join(text.strip().split())


def parse_counter_from_text(text: str) -> int | None:
    match = re.search(r"(-?\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


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
        # Instruct the LLM to emit a one-line counter string. Provide prior context.
        system_prompt = (
            "You are the Vibing Webmaster. Emit a single line of plain text only."
        )
        user_prompt = (
            f"Previous counter: {prev_counter}. Increment by 1 and output exactly one"
            f" line, plain text, in the format 'Counter: <number>'. Do not add"
            f" extra words.\n\nProject prompt:\n{prompt_text}"
        )
        try:
            new_content = call_llm_generate_content(model=model, system_prompt=system_prompt, user_prompt=user_prompt)
            parsed = parse_counter_from_text(new_content)
            if parsed is not None and parsed >= 0:
                next_counter = parsed
        except Exception as e:
            # Fallback to deterministic counter if LLM fails
            new_content = f"Counter: {next_counter}"
            print(f"LLM error, falling back to counter: {e}")
    else:
        # Pure deterministic mode
        new_content = f"Counter: {next_counter}"

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
    p.add_argument("--model", default=os.getenv("MODEL", "gpt-4o-mini"), help="OpenAI model name")
    p.add_argument("--dry-run", action="store_true", help="Compute without writing files")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(mode=args.mode, dry_run=args.dry_run, model=args.model)


