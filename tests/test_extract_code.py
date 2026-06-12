from dualcore.agents import extract_code


def test_extracts_single_python_block():
    text = "## Analysis\nstuff\n## Implementation\n```python\ndef f():\n    return 1\n```\n## Assumptions\nNone"
    assert extract_code(text) == "def f():\n    return 1"


def test_prefers_longest_python_block():
    text = "```python\nx = 1\n```\nlater\n```python\ndef big():\n    return 1 + 2 + 3\n```"
    assert "def big()" in extract_code(text)


def test_falls_back_to_any_fenced_block():
    text = "```\nplain code\n```"
    assert extract_code(text) == "plain code"


def test_falls_back_to_whole_text_when_no_fence():
    text = "def f():\n    return 1"
    assert extract_code(text) == "def f():\n    return 1"


def test_ignores_language_tag_variants():
    text = "```py\ndef g():\n    return 2\n```"
    assert extract_code(text) == "def g():\n    return 2"
