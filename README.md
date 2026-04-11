# DualCore — Dual Agentic AI Coding Assistant

A fully agentic AI system where two LLM agents collaborate iteratively:
- **Agent A (Coder)**: Writes Python code based on your requirement, then refines it
- **Agent B (Debugger)**: Reviews Agent A's code for bugs, edge cases, security issues, and quality

<img width="2872" height="1791" alt="image" src="https://github.com/user-attachments/assets/ccdf70fa-3dbc-4729-9a39-08216483dd39" />



**Powered by Groq (100% free, no credit card required)** using Llama 3.3 70B.

---

## Quick Start

### 1. Get a free Groq API key
1. Go to [console.groq.com](https://console.groq.com)
2. Sign up (no credit card needed)
3. Create an API key

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set up environment
```bash
cp .env.example .env
# Edit .env and paste your Groq API key
```

### 4. Run
```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## How It Works

```
User Requirement
      │
      ▼
┌─────────────┐      Round 1       ┌──────────────┐
│  Agent A    │  ─── code ──►      │   Agent B    │
│  (Coder)    │  ◄── feedback ──   │  (Debugger)  │
└─────────────┘      Round 2       └──────────────┘
      │  ─── refined code ──►            │
      │  ◄── final verdict ──            │
      ▼
Final Code (tested, reviewed, production-ready)
```

Each round:
1. **Agent A** writes/refines Python code with type hints, docstrings, error handling
2. **Agent B** reviews for: correctness, edge cases, security, performance, code quality

You can configure 1, 2, or 3 rounds from the UI.

---

## Project Structure
```
dualcore/
├── app.py              # Flask backend + Groq API + agent logic
├── templates/
│   └── index.html      # Frontend UI (dark terminal aesthetic)
├── requirements.txt
├── .env.example
└── README.md
```

## Rate Limits (Groq Free Tier)
- ~1,000 requests/day on Llama 3.3 70B
- ~6,000 tokens/minute
- Each agent run uses ~4-6 API calls (2 per round × agents)

## Tech Stack
- **Backend**: Python, Flask, Groq SDK
- **Frontend**: Vanilla HTML/CSS/JS, highlight.js (syntax highlighting)
- **LLM**: Llama 3.3 70B via Groq (free)
- **Streaming**: Server-Sent Events (SSE) for real-time agent output
