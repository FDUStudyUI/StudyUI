import re
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "src/materials_quality/agent/ui/index.html"


def test_stream_completion_uses_the_canonical_final_message_renderer():
    html = UI.read_text(encoding="utf-8")

    assert re.search(
        r"""function\s+splitEmbeddedThinking\(\s*text\s*,\s*reasoning\s*=\s*(['"])\1\s*\)""", html
    )
    assert re.search(r"""addMessage\(\s*(['"])assistant\1\s*,\s*result\.message\s*,\s*result\s*\)""", html)
    assert "streamedRich" not in html
    assert not re.search(r"answer\s*\.\s*replaceChildren\(\s*\.\.\.nodes\s*\)", html)
