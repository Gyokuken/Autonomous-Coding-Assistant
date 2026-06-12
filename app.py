"""DualCore — Flask entrypoint.

Thin HTTP/SSE layer over :class:`dualcore.orchestrator.Orchestrator`. All the
real logic (agents, sandbox, loop) lives in the ``dualcore`` package.
"""

from __future__ import annotations

import json

from flask import Flask, Response, render_template, request, stream_with_context

from dualcore.config import (
    AVAILABLE_MODELS,
    VALID_MODELS,
    VALID_PROFILES,
    ConfigError,
    load_settings,
)
from dualcore.llm import GroqLLM
from dualcore.orchestrator import Orchestrator
from dualcore.sandbox import get_sandbox

settings = load_settings()
sandbox = get_sandbox(settings)

# Build the LLM eagerly so a missing key is reported at startup, but keep the app
# bootable (the UI loads and explains the problem) rather than crashing.
llm: GroqLLM | None
startup_error: str | None
try:
    llm = GroqLLM(settings)
    startup_error = None
except ConfigError as exc:
    llm, startup_error = None, str(exc)
    print(f"[DualCore] WARNING: {exc}")

ok, message = sandbox.health_check()
print(f"[DualCore] sandbox driver={settings.sandbox_driver} ({message})")
if not ok:
    print(f"[DualCore] NOTE: {message}")

app = Flask(__name__)


def sse_event(event: str, data: dict) -> str:
    """Format one Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def model_options() -> list[tuple[str, str]]:
    """Selector options; include the configured default if it's a custom model."""
    options = list(AVAILABLE_MODELS)
    if settings.model not in {mid for mid, _ in options}:
        options.insert(0, (settings.model, settings.model + " · custom"))
    return options


@app.route("/")
def index():
    return render_template(
        "index.html",
        model=settings.model,
        driver=settings.sandbox_driver,
        max_rounds=settings.max_rounds,
        profiles=sorted(VALID_PROFILES),
        models=model_options(),
    )


@app.route("/health")
def health():
    ok, message = sandbox.health_check()
    return {
        "status": "ok",
        "llm_ready": llm is not None,
        "sandbox": {"driver": settings.sandbox_driver, "ok": ok, "message": message},
    }


@app.route("/run", methods=["POST"])
def run_agents():
    if llm is None:
        return {"error": startup_error or "LLM is not configured."}, 503

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {"error": "Request body must be JSON."}, 400

    requirement = str(data.get("requirement", "")).strip()
    instructions = str(data.get("instructions", "")).strip()
    profile = str(data.get("profile", "basic")).strip().lower()
    model = str(data.get("model", "")).strip() or settings.model

    if not requirement:
        return {"error": "No requirement provided."}, 400
    if len(requirement) > settings.max_requirement_chars:
        return {"error": f"Requirement too long (max {settings.max_requirement_chars})."}, 400
    if len(instructions) > settings.max_instructions_chars:
        return {"error": f"Instructions too long (max {settings.max_instructions_chars})."}, 400
    if profile not in VALID_PROFILES:
        return {"error": f"Unknown profile {profile!r}."}, 400
    if model not in (VALID_MODELS | {settings.model}):
        return {"error": f"Unknown model {model!r}."}, 400

    try:
        rounds = int(data.get("rounds", 2))
    except (TypeError, ValueError):
        return {"error": "rounds must be an integer."}, 400
    rounds = max(1, min(rounds, settings.max_rounds))

    orchestrator = Orchestrator(llm, sandbox, settings, model=model)

    def generate():
        for event in orchestrator.run(requirement, instructions, profile, rounds):
            yield sse_event(str(event.get("type", "message")), event)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    app.run(debug=settings.debug, port=settings.port, threaded=True)
