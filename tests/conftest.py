"""Shared test setup.

Ensures the app is importable without a real Groq key and that tests use the
subprocess sandbox (no Docker daemon required in CI).
"""

import os

os.environ.setdefault("GROQ_API_KEY", "test-dummy-key")
os.environ.setdefault("SANDBOX", "subprocess")
