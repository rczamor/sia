"""Store documents: Markdown + YAML front matter (the canonical serialization).

Markdown is the canonical store format by design decision: token-cheap inside
budgeted context builds, hand-editable, Obsidian-compatible, and — load-bearing —
human-reviewable git diffs are the trust gate against memory poisoning. HTML is
used for *rendered surfaces* (artifacts, dashboards, review diffs), never storage.
The serializer is a seam: an alternative StoreSerializer can be plugged in.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import yaml

FRONT_MATTER_DELIMITER = "---"


@dataclass
class StoreDocument:
    path: str
    front: dict[str, Any] = field(default_factory=dict)
    body: str = ""

    @property
    def kind(self) -> str:
        if self.path.startswith("knowledge/"):
            return "topic"
        if self.path.startswith("skills/"):
            return "skill"
        if self.path.startswith("profile/"):
            return "profile"
        if self.path.startswith("theses/"):
            return "thesis"
        if self.path.startswith("tensions/"):
            return "tension"
        return "other"

    def section(self, heading: str) -> str:
        """Return the text under a ``## heading`` up to the next ``## ``."""
        lines = self.body.split("\n")
        collected: list[str] = []
        inside = False
        for line in lines:
            if line.strip().lower() == f"## {heading}".lower():
                inside = True
                continue
            if inside and line.startswith("## "):
                break
            if inside:
                collected.append(line)
        return "\n".join(collected).strip()


@runtime_checkable
class StoreSerializer(Protocol):
    extension: str

    def loads(self, path: str, text: str) -> StoreDocument: ...

    def dumps(self, document: StoreDocument) -> str: ...


class MarkdownSerializer:
    extension = ".md"

    def loads(self, path: str, text: str) -> StoreDocument:
        front: dict[str, Any] = {}
        body = text
        if text.startswith(FRONT_MATTER_DELIMITER):
            parts = text.split(FRONT_MATTER_DELIMITER, 2)
            if len(parts) == 3:
                loaded = yaml.safe_load(parts[1]) or {}
                if isinstance(loaded, dict):
                    front = loaded
                    body = parts[2].lstrip("\n")
        return StoreDocument(path=path, front=front, body=body)

    def dumps(self, document: StoreDocument) -> str:
        if not document.front:
            return document.body
        front_text = yaml.safe_dump(document.front, sort_keys=False, allow_unicode=True).strip()
        return f"{FRONT_MATTER_DELIMITER}\n{front_text}\n{FRONT_MATTER_DELIMITER}\n\n{document.body}"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
