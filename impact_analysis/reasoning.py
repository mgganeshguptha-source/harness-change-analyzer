"""
reasoning.py — the reasoning backend for the Impact Analyzer.

Two interchangeable implementations behind one function signature
`reason(prompt: str) -> dict`:

  * mock_reason   — returns deterministic fake JSON. No SDK, no credits.
                    Lets the whole flow run end-to-end today.
  * copilot_reason — REAL call via the Copilot SDK, matching the engine's
                    sdk_runner.py usage exactly:
                      CopilotClient(working_directory=..., github_token=...)
                        -> create_session(model=...)
                        -> session.on(handler); session.send(prompt)
                      collecting assistant.message text, then parsing JSON.

Select with HARNESS_REASONING=mock|copilot (default: mock), or pass the
function explicitly to analyze().

The mock reads an optional fixture file (HARNESS_MOCK_FIXTURE) so you can
script different scenarios; otherwise it emits a generic single-provider,
single-consumer shape derived from the prompt text.
"""

from __future__ import annotations

import asyncio
import json
import os
import re

# Same default model string the engine uses; override via env.
DEFAULT_MODEL = os.environ.get("HARNESS_ANALYSIS_MODEL", "gpt-5.4-mini")
SESSION_TIMEOUT_S = int(os.environ.get("HARNESS_ANALYSIS_TIMEOUT", "300"))


# ---------------------------------------------------------------------
# JSON extraction (shared)
# ---------------------------------------------------------------------
def parse_json(text: str) -> dict:
    """Parse a JSON object out of model text, tolerating code fences/prose."""
    cleaned = text.strip()
    # strip leading/trailing code fences if present
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    # if there is surrounding prose, grab the outermost {...}
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


# ---------------------------------------------------------------------
# MOCK backend
# ---------------------------------------------------------------------
def mock_reason(prompt: str, model: str | None = None, parse: bool = True):
    """Deterministic fake reasoning. No SDK. Optionally load a fixture file."""
    fixture = os.environ.get("HARNESS_MOCK_FIXTURE")
    if fixture and os.path.exists(fixture):
        with open(fixture, "r", encoding="utf-8") as fh:
            return json.load(fh)

    # Derive a plausible shape from the repo names present in the prompt, so a
    # smoke run produces something schema-valid without any real analysis.
    repo_names = re.findall(r"### repo: ([A-Za-z0-9._-]+)", prompt)
    provider = repo_names[0] if repo_names else "example-provider"
    consumers = repo_names[1:3]  # up to two consumers

    return {
        "provider": {
            "repo": provider,
            "contract": f"api/{provider}.yaml",
            "contract_version": "v2",
        },
        "consumers": [
            {"repo": r, "evidence": "MOCK: referenced in prompt repo list"}
            for r in consumers
        ],
        "potentially_affected": [],
        "dependencies": [
            {"from": provider, "to": r} for r in consumers
        ],
        "contract_change": {"type": "backward_compatible"},
        "confidence": 80,
        "clarifications_needed": [],
        "assumptions": ["MOCK: assumed standard provider/consumer roles"],
        "evidence": [
            "MOCK reasoning — replace by setting HARNESS_REASONING=copilot",
            f"provider inferred as first candidate repo: {provider}",
        ],
    }


# ---------------------------------------------------------------------
# REAL Copilot backend  (matches engine/sdk_runner.py usage)
# ---------------------------------------------------------------------
def copilot_reason(prompt: str, model: str | None = None, parse: bool = True):
    """Real reasoning via the Copilot SDK.
    parse=True  -> parse the reply as JSON and return a dict (analysis).
    parse=False -> return the raw text reply (e.g. Markdown per-repo stories)."""
    return asyncio.run(_copilot_reason_async(prompt, model or DEFAULT_MODEL, parse))


async def _copilot_reason_async(prompt: str, model: str, parse: bool = True):
    # Lazy import so the module loads on machines without the SDK (mock path).
    from copilot import CopilotClient  # noqa: F401  (github-copilot-sdk)

    # Auth exactly as the engine does: prefer an explicit token in CI, fall
    # back to the logged-in Copilot CLI locally.
    ci_token = (
        os.environ.get("COPILOT_GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
    )
    client_kwargs: dict = {"working_directory": os.getcwd()}
    if ci_token:
        client_kwargs["github_token"] = ci_token
    else:
        client_kwargs["use_logged_in_user"] = True

    last_message = {"text": ""}
    seen_events: dict = {}
    errors: list[str] = []

    # NOTE: analysis is a READ-ONLY single-turn reasoning call. We deliberately
    # do NOT pass on_permission_request (that is the coding-phase write-boundary
    # enforcement); the analyzer never writes to any repo.
    async with CopilotClient(**client_kwargs) as client:
        async with await client.create_session(model=model) as session:
            done = asyncio.Event()

            def on_event(event):
                t = event.type.value
                seen_events[t] = seen_events.get(t, 0) + 1
                if t == "assistant.message":
                    try:
                        last_message["text"] = event.data.content or ""
                    except Exception:  # noqa: BLE001
                        pass
                elif "error" in t.lower():
                    try:
                        errors.append(
                            f"{t}: {getattr(event.data, 'message', str(event.data))[:300]}")
                    except Exception:  # noqa: BLE001
                        errors.append(t)
                if t in ("session.idle", "session.completed",
                         "turn.completed", "session.error"):
                    done.set()

            session.on(on_event)
            await session.send(prompt)
            try:
                await asyncio.wait_for(done.wait(), timeout=SESSION_TIMEOUT_S)
            except asyncio.TimeoutError:
                errors.append(
                    f"timed out after {SESSION_TIMEOUT_S}s waiting for a "
                    f"terminal event; events seen: {seen_events}")

    if not last_message["text"]:
        detail = "; ".join(errors) if errors else f"no assistant.message; events={seen_events}"
        raise RuntimeError(f"Copilot reasoning produced no output: {detail}")

    if not parse:
        return last_message["text"]
    try:
        return parse_json(last_message["text"])
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Copilot reply was not valid JSON ({e}). "
            f"First 300 chars: {last_message['text'][:300]}")


# ---------------------------------------------------------------------
# selector
# ---------------------------------------------------------------------
def get_reasoner(name: str | None = None):
    """Return the reasoning function by name / env. Default: mock."""
    choice = (name or os.environ.get("HARNESS_REASONING", "mock")).lower()
    if choice == "copilot":
        return copilot_reason
    if choice == "mock":
        return mock_reason
    raise ValueError(f"unknown reasoning backend: {choice}")
