# DualCore — a grounded dual-agent coding system

Two LLM agents collaborate to write **working** code — and unlike most "AI pair"
demos, the reviewer doesn't just *opine*, it **runs the code**.

- **Agent A — Coder** writes the implementation, then refines it.
- **Agent B — Test Designer** writes an *executable* pytest suite (normal, edge,
  and adversarial cases — it invents the scenarios itself).
- **The Sandbox** actually executes the code against those tests in isolation and
  reports real pass/fail with tracebacks.
- The loop feeds **real failures** back to the Coder until the suite is green (or
  it runs out of rounds), then Agent B writes a final review.


<img width="2880" height="1800" alt="image" src="https://github.com/user-attachments/assets/c62e9a1d-8531-4fe4-846c-4d005429a4b5" />


The result is code that has been *executed and tested*, not just eyeballed by a
second model.

> Powered by **Groq** (free tier) running Llama 3.3 70B.

---

## Why it's different

Most "dual agent" coding demos are two chatbots taking turns — the "debugger"
never executes anything, so it hallucinates bugs and misses real ones. DualCore
closes the loop with a real execution sandbox:

```
Requirement  (+ optional instructions, + profile: basic | ml)
      │
 ┌────▼─────┐   solution.py    ┌───────────────┐   test_solution.py
 │ Coder (A)│ ───────────────► │ Test Designer │ ──────────────┐
 └────▲─────┘                  │      (B)      │                │
      │                        └───────────────┘                ▼
      │ real tracebacks                                 ┌────────────────┐
      │                                                 │    SANDBOX     │
      └──────────────  fix & repeat until green  ◄───── │ docker | subproc│
                       (early-exit when passing)        └────────┬───────┘
                                                                 │
                                          Final review  ◄────────┘
```

---

## Features

- **Grounded execution loop** — code is run against generated tests every round.
- **Autonomous test generation** — Agent B derives test cases from the
  requirement, including edge/adversarial inputs.
- **ML / tensor profile** — switch to the `ml` profile and the agents write and
  test PyTorch code: output shapes, dtypes, gradient flow (`loss.backward()`),
  parameter counts, determinism under a fixed seed.
- **Custom instructions** — steer the agents ("use only recursion", "implement a
  residual block and verify gradient flow", …).
- **Pluggable sandbox** — `docker` (hardened, for deploys) or `subprocess`
  (fast, for trusted local dev) behind one interface.
- **Live streaming UI** — three lanes (Coder · Test Designer · Runtime) stream
  tokens and show real test results with pass/fail badges and tracebacks.
- **Early-exit** — stops as soon as the suite is green; no wasted API calls.

---

## Tech stack

| Layer     | Choice                                                |
|-----------|-------------------------------------------------------|
| Backend   | Python 3.12, Flask, Server-Sent Events                |
| LLM       | Groq SDK · Llama 3.3 70B (free)                        |
| Execution | Docker (prod) / `subprocess` (dev), pytest + json-report |
| Frontend  | Vanilla HTML/CSS/JS, highlight.js                      |
| Tests/CI  | pytest, GitHub Actions                                 |

---

## Quick start (local dev)

```bash
pip install -r requirements.txt
cp .env.example .env          # then paste your free Groq key from console.groq.com
```

Set the sandbox to subprocess for local dev (no Docker needed):

```bash
# in .env
GROQ_API_KEY=gsk_...
SANDBOX=subprocess
```

Run it:

```bash
python app.py
# open http://localhost:5000
```

> `subprocess` mode runs generated code as a child process on your machine. It is
> fine for trusted local use (the child's environment is scrubbed so it can't read
> your API key), but **never expose it on a public URL** — use Docker for that.

---

## The ML / tensor profile

Pick **ML · PyTorch** in the UI (or send `"profile": "ml"`). Now the agents may
use `numpy`/`torch`, and the Test Designer additionally verifies tensor behaviour.
Example instruction:

> *Implement a PyTorch residual block (Conv-BN-ReLU twice + skip connection) as
> an `nn.Module`.* — and the suite will check output shape, that it runs on a
> batch, and that gradients flow.

The `ml` profile requires the `dualcore-sandbox:ml` image (Docker) — see below.

---

## Production / Docker deploy

The Docker driver runs each execution in a throwaway container with **no network,
dropped capabilities, a read-only root FS, and memory/CPU/pid limits**.

**1. Build the sandbox images** (on the host):

```bash
python scripts/build_sandbox_images.py        # basic + ml
python scripts/build_sandbox_images.py basic  # or just one
```

**2a. Run fully containerized (docker-compose):**

```bash
export GROQ_API_KEY=gsk_...
docker compose up --build
# open http://localhost:8000
```

The app container talks to the host Docker daemon (mounted socket) to launch the
sandbox containers. See the security note in `docker-compose.yml`.

**2b. Or run the app on a Docker host directly:**

```bash
SANDBOX=docker gunicorn app:app --bind 0.0.0.0:8000 --timeout 300 --workers 2 --threads 4
```

---

## Configuration

All via environment variables (or `.env`):

| Variable          | Default                     | Description                                  |
|-------------------|-----------------------------|----------------------------------------------|
| `GROQ_API_KEY`    | —                           | **Required.** Free key from Groq.            |
| `SANDBOX`         | `docker`                    | `docker` or `subprocess`.                    |
| `MODEL`           | `llama-3.3-70b-versatile`   | Any Groq chat model.                         |
| `MAX_ROUNDS`      | `4`                         | Max refine rounds.                           |
| `EXEC_TIMEOUT`    | `30`                        | Seconds per sandbox run.                     |
| `MEM_LIMIT_MB`    | `512`                       | Docker memory cap.                           |
| `CPU_LIMIT`       | `1.0`                       | Docker CPU cap.                              |
| `FLASK_DEBUG`     | `0`                         | Enable Flask debugger (dev only).            |
| `PORT`            | `5000`                      | Dev-server port.                             |

---

## Testing

```bash
python -m pytest -q
```

Covers code extraction, pytest-report parsing, the sandbox (including a test that
proves generated code **cannot read `GROQ_API_KEY`**), the full fix-loop with a
fake LLM, early-exit, and Flask validation. CI runs on every push/PR.

---

## Project structure

```
app.py                       # Flask entrypoint (routes + SSE)
dualcore/
  config.py                  # env loading + validation
  llm.py                     # Groq wrapper (+ streaming)
  agents.py                  # Coder / Test Designer / Reviewer prompts + code extraction
  orchestrator.py            # the grounded loop
  sandbox/
    base.py                  # Sandbox ABC, ExecutionResult, pytest-json parsing
    subprocess_sandbox.py    # dev driver
    docker_sandbox.py        # prod driver
templates/index.html         # 3-lane streaming UI
sandbox-images/              # Dockerfiles for the basic + ml sandbox images
scripts/build_sandbox_images.py
tests/                       # pytest suite
Dockerfile, docker-compose.yml, Procfile
```

---

## Security notes

- Generated code is untrusted. The **Docker driver** is the safe way to run it
  publicly (network off, caps dropped, read-only FS, resource limits, ephemeral).
- The **subprocess driver** is for trusted local use only; it scrubs the child's
  environment (no API key leak) and kills runaway processes, but does not isolate
  the filesystem.
- The compose setup mounts the Docker socket (host-root-equivalent). Fine for a
  personal deploy; use a socket-proxy/rootless Docker for multi-tenant use.

---

## Roadmap

- Let the Test Designer revise its own suite when code and tests genuinely
  disagree on an ambiguous spec.
- Persist runs (SQLite) with shareable links and `.py` export.
- Distributed rate limiting (Redis) for public multi-worker deploys.
- More languages and sandbox profiles.

## Groq free-tier limits

~1,000 requests/day on Llama 3.3 70B. Each run uses ~3–6 calls (code + tests +
fixes + review), and early-exit keeps it lean.
