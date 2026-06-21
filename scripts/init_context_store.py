#!/usr/bin/env python
"""Initialize the git-backed Sia context store and optional remote mirror."""

import argparse
import asyncio

from app.config import settings
from app.context.store.gitstore import GitContextStore, StoreError
from app.context.store.layout import scaffold_store


async def init_context_store(
    path: str | None = None,
    remote: str | None = None,
    push: bool = True,
) -> dict:
    store = GitContextStore(path or settings.context_store_path)
    sha = await scaffold_store(store)
    result = {
        "path": str(store.root),
        "head": sha,
        "pushed": False,
        "remote": remote or settings.context_store_remote or "",
    }

    if push and result["remote"]:
        def _push():
            store._git("push", "-u", result["remote"], "main")

        await asyncio.to_thread(_push)
        result["pushed"] = True
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize Sia's separate git-backed context store."
    )
    parser.add_argument(
        "--path",
        default=None,
        help="Context store path. Defaults to CONTEXT_STORE_PATH.",
    )
    parser.add_argument(
        "--remote",
        default=None,
        help="Git remote URL or name to push main to. Defaults to CONTEXT_STORE_REMOTE.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Initialize only; do not push even if a remote is configured.",
    )
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    try:
        result = await init_context_store(
            path=args.path,
            remote=args.remote,
            push=not args.no_push,
        )
    except StoreError as exc:
        print(f"context store init failed: {exc}")
        return 1

    print(f"context store: {result['path']}")
    print(f"head: {result['head']}")
    if result["remote"]:
        print(f"remote: {result['remote']}")
        print(f"pushed: {str(result['pushed']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
