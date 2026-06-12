"""Verify the vendored frontend assets against their pinned hashes.

Guards against silent asset upgrades or tampering: the admin UI executes only
these exact files. Runs in CI (security job) and via pytest. To upgrade an
asset deliberately: fetch the new version from the project's release tag,
update VENDOR_MANIFEST here AND docs/supply-chain.md in the same commit.
"""

import hashlib
import sys
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "vendor"

# filename -> (version, sha256). Source URLs are recorded in docs/supply-chain.md.
VENDOR_MANIFEST = {
    "pico.min.css": (
        "2.0.6",
        "dd5fd5591afd81ee21dcc117ad85c014dc3f1f19dc2d7b7d101ea0acc29274c2",
    ),
    "htmx.min.js": (
        "2.0.4",
        "e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447",
    ),
    "cytoscape.min.js": (
        "3.30.2",
        "83e8c54a6bec655bfd81df07df605649c268af69aeca67a5ea2da54ea42dac81",
    ),
}


def verify() -> list[str]:
    """Return a list of problems; empty means every asset matches its pin."""
    problems = []
    for name, (version, expected) in VENDOR_MANIFEST.items():
        path = VENDOR_DIR / name
        if not path.is_file():
            problems.append(f"{name}: missing from {VENDOR_DIR}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            problems.append(
                f"{name}: sha256 mismatch (expected {expected[:12]}… for v{version}, "
                f"got {actual[:12]}…) — assets must not change without updating the "
                "manifest and docs/supply-chain.md"
            )
    unexpected = {p.name for p in VENDOR_DIR.glob("*")} - set(VENDOR_MANIFEST)
    for name in sorted(unexpected):
        problems.append(f"{name}: present in vendor/ but not in the manifest")
    return problems


if __name__ == "__main__":
    issues = verify()
    if issues:
        print("vendor asset verification FAILED:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        sys.exit(1)
    for name, (version, _) in VENDOR_MANIFEST.items():
        print(f"ok  {name}  v{version}")
