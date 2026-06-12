"""Vocabulary guard: retired terminology must not reappear in code, prompts, or UI.

Per the Platform Document terminology guide: the product is "Sia" (category:
Context Engine); the pillar label is "Context Architecture"; the architecture is
the four-layer model, not "three-phase".
"""

from pathlib import Path

RETIRED_TERMS = [
    "Context Layer Engine",
    "Context Intelligence",
    "three-phase",
]

SCANNED_GLOBS = ["app/**/*.py", "templates/**/*.html", "README.md", "pyproject.toml"]


def test_no_retired_vocabulary():
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for pattern in SCANNED_GLOBS:
        for path in root.glob(pattern):
            content = path.read_text(encoding="utf-8")
            for term in RETIRED_TERMS:
                if term in content:
                    offenders.append(f"{path.relative_to(root)}: '{term}'")
    assert not offenders, "Retired vocabulary found:\n" + "\n".join(offenders)


def test_classification_prompt_uses_current_pillar_label():
    from app.prompts.source_analyst import CLASSIFY_AND_SUMMARIZE

    assert "Context Architecture" in CLASSIFY_AND_SUMMARIZE
    # Stored enum value is unchanged for data compatibility
    assert "context_layers" in CLASSIFY_AND_SUMMARIZE
