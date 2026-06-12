"""Intake quarantine: heuristic screening of untrusted content before it can ever
reach consolidation.

Quarantined items are stored (auditable) but excluded from every consolidation
query; only an operator clearing the flag releases them. This is the first line of
the memory-poisoning defense — the second is the human review gate on consolidation
branches.
"""

import re

MAX_CONTENT_BYTES = 400_000

# Marker patterns that legitimate articles essentially never contain but prompt
# injection payloads routinely do.
INJECTION_PATTERNS = [
    re.compile(r"ignore (all |any )?(previous|prior|above) (instructions|context|prompts)", re.I),
    re.compile(r"disregard (the|all|your) (above|previous|prior|system)", re.I),
    re.compile(r"you are now (DAN|jailbroken|unrestricted)", re.I),
    re.compile(r"<\|im_(start|end)\|>"),
    re.compile(r"\[/?(SYSTEM|INST)\]", re.I),
    re.compile(r"reveal (your|the) (system prompt|instructions|api key)", re.I),
    re.compile(r"(exfiltrate|send|post) .{0,40}(credentials|secrets|api.?keys)", re.I),
]


def quarantine_reason(content: str, pillars: list[str] | None = None) -> str | None:
    """Return a human-readable reason to quarantine, or None if the item is clean."""
    if len(content.encode("utf-8", errors="ignore")) > MAX_CONTENT_BYTES:
        return f"content exceeds {MAX_CONTENT_BYTES} bytes"
    scan_window = content[:50_000]
    for pattern in INJECTION_PATTERNS:
        if pattern.search(scan_window):
            return f"prompt-injection marker: {pattern.pattern[:60]}"
    if pillars is not None and not pillars:
        return "classifier returned no pillar (off-domain content)"
    return None
