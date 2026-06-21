"""Git-backed context store (the default ContextStoreBackend).

Design constraints:
- The main working tree NEVER leaves the main branch; review branches are written
  through temporary worktrees, so web reads and worker writes cannot race a checkout.
- All mutating operations queue on an event-loop lock before entering the worker
  thread, then serialize cross-process on an fcntl lock file.
- Untrusted-derived writes land on ``consolidation/<date>`` branches; only a human
  approval merges them (the memory-poisoning trust gate). Owner-tier writes commit
  straight to main.
- Pruning is an archive commit, never a deletion of history.
"""

import asyncio
import fcntl
import logging
import os
# B404: subprocess is how the store drives git; every call goes through _git()
# below — list args, no shell, fixed executable.
import subprocess  # nosec B404
import tempfile
import threading
import weakref
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.config import settings

logger = logging.getLogger(__name__)

GIT_AUTHOR = "Sia <sia@localhost>"
REVIEW_BRANCH_PREFIX = "consolidation/"
_ASYNC_MUTATION_LOCKS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[Path, asyncio.Lock]
] = weakref.WeakKeyDictionary()
_ASYNC_MUTATION_LOCKS_GUARD = threading.Lock()


class StoreError(RuntimeError):
    pass


def _async_mutation_lock_for(root: Path) -> asyncio.Lock:
    """One in-process async gate per event loop + store root.

    Tests create fresh event loops, so a plain module-level asyncio.Lock would
    eventually bind to the wrong loop. The WeakKeyDictionary keeps loop-local
    locks and lets closed test loops disappear.
    """
    loop = asyncio.get_running_loop()
    root_key = root.resolve()
    with _ASYNC_MUTATION_LOCKS_GUARD:
        locks = _ASYNC_MUTATION_LOCKS.setdefault(loop, {})
        lock = locks.get(root_key)
        if lock is None:
            lock = asyncio.Lock()
            locks[root_key] = lock
        return lock


def _safe_target(root: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` under ``root``, refusing any path that escapes it.

    Store paths can originate from LLM output (topic slugs, skill slugs, pillars),
    so an injected ``../../`` or absolute path must never write outside the store.
    """
    if rel_path.startswith("/") or "\x00" in rel_path:
        raise StoreError(f"unsafe store path: {rel_path!r}")
    target = (root / rel_path).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise StoreError(f"store path escapes root: {rel_path!r}")
    # never write into the repo's own metadata directory
    if ".git" in target.relative_to(root_resolved).parts:
        raise StoreError(f"store path targets .git: {rel_path!r}")
    return target


@runtime_checkable
class ContextStoreBackend(Protocol):
    async def read(self, path: str, ref: str = "HEAD") -> str | None: ...

    async def list_paths(self, prefix: str = "", ref: str = "HEAD") -> list[str]: ...

    async def commit(
        self, files: dict[str, str | None], message: str, branch: str | None = None
    ) -> str: ...

    async def head_sha(self) -> str: ...

    async def diff(self, branch: str) -> str: ...

    async def list_review_branches(self) -> list[str]: ...

    async def merge_branch(self, branch: str) -> str: ...

    async def delete_branch(self, branch: str) -> None: ...


class GitContextStore:
    """Local git repository store. ``root`` defaults to settings.context_store_path."""

    def __init__(self, root: str | None = None):
        self.root = Path(root or settings.context_store_path)

    # --- internals (sync, run via to_thread) ---

    def _git(
        self,
        *args: str,
        cwd: Path | None = None,
        check: bool = True,
        return_result: bool = False,
    ):
        # B603/B607: list args (no shell), fixed "git" executable resolved from
        # PATH inside our container; path arguments are store-relative and
        # validated by callers (no untrusted strings reach argv).
        result = subprocess.run(  # nosec B603 B607
            # Self-contained repo behavior regardless of host/global git config:
            # no commit signing, no template hooks.
            ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=", *args],
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Sia",
                "GIT_AUTHOR_EMAIL": "sia@localhost",
                "GIT_COMMITTER_NAME": "Sia",
                "GIT_COMMITTER_EMAIL": "sia@localhost",
            },
        )
        if check and result.returncode != 0:
            raise StoreError(
                f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return result if return_result else result.stdout

    @contextmanager
    def _lock(self):
        lock_path = self.root / ".sia" / "lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _ensure_initialized(self) -> None:
        if (self.root / ".git").exists():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self._git("init", "--initial-branch=main")
        logger.info("Initialized context store at %s", self.root)

    def _commit_sync(self, files: dict[str, str | None], message: str, branch: str | None) -> str:
        with self._lock():
            self._ensure_initialized()
            if branch is None:
                return self._write_and_commit(self.root, files, message)
            # Review branch: never touch the main working tree.
            # Prune first: a prior worker crash (or a failed remove) can leave a
            # stale .git/worktrees entry that otherwise blocks 'worktree add'
            # ("branch already checked out") forever.
            self._git("worktree", "prune", check=False)
            base = "main" if self._branch_exists("main") else None
            with tempfile.TemporaryDirectory(prefix="sia-worktree-") as tmp:
                if self._branch_exists(branch):
                    self._git("worktree", "add", tmp, branch)
                elif base:
                    self._git("worktree", "add", "-b", branch, tmp, base)
                else:
                    raise StoreError("Cannot branch before the first commit on main")
                try:
                    return self._write_and_commit(Path(tmp), files, message)
                finally:
                    self._git("worktree", "remove", "--force", tmp, check=False)

    def _write_and_commit(self, tree: Path, files: dict[str, str | None], message: str) -> str:
        for rel_path, content in files.items():
            target = _safe_target(tree, rel_path)
            if content is None:
                if target.exists():
                    self._git("rm", "-q", "--", rel_path, cwd=tree)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                self._git("add", "--", rel_path, cwd=tree)
        staged = self._git("diff", "--cached", "--name-only", cwd=tree)
        if not staged.strip():
            return self._git("rev-parse", "HEAD", cwd=tree).strip()
        self._git("commit", "-q", "-m", message, cwd=tree)
        return self._git("rev-parse", "HEAD", cwd=tree).strip()

    def _branch_exists(self, branch: str) -> bool:
        result = self._git("rev-parse", "--verify", "--quiet", branch, check=False)
        return bool(result.strip())

    # --- async API ---

    async def read(self, path: str, ref: str = "HEAD") -> str | None:
        def _read():
            if not (self.root / ".git").exists():
                return None
            target = _safe_target(self.root, path)  # refuse paths escaping the store
            if ref == "HEAD":
                return target.read_text(encoding="utf-8") if target.exists() else None
            out = self._git("show", f"{ref}:{path}", check=False)
            return out or None

        return await asyncio.to_thread(_read)

    async def list_paths(self, prefix: str = "", ref: str = "HEAD") -> list[str]:
        def _list():
            if not (self.root / ".git").exists() or not self._branch_exists("main"):
                return []
            out = self._git("ls-tree", "-r", "--name-only", ref, check=False)
            return [p for p in out.splitlines() if p.startswith(prefix)]

        return await asyncio.to_thread(_list)

    async def commit(
        self, files: dict[str, str | None], message: str, branch: str | None = None
    ) -> str:
        async with _async_mutation_lock_for(self.root):
            return await asyncio.to_thread(self._commit_sync, files, message, branch)

    async def head_sha(self) -> str:
        def _head():
            self._ensure_initialized()
            return self._git("rev-parse", "HEAD", check=False).strip() or "empty"

        return await asyncio.to_thread(_head)

    async def diff(self, branch: str) -> str:
        return await asyncio.to_thread(self._git, "diff", f"main...{branch}")

    async def list_review_branches(self) -> list[str]:
        def _branches():
            if not (self.root / ".git").exists():
                return []
            out = self._git(
                "branch", "--list", f"{REVIEW_BRANCH_PREFIX}*", "--format=%(refname:short)"
            )
            return [b.strip() for b in out.splitlines() if b.strip()]

        return await asyncio.to_thread(_branches)

    async def merge_branch(self, branch: str) -> str:
        def _merge():
            with self._lock():
                result = self._git(
                    "merge", "--no-ff", "-q", "-m", f"review: approve {branch}", branch,
                    check=False, return_result=True,
                )
                if result.returncode != 0:
                    # Leave the store clean: abort the half-applied merge before
                    # surfacing the conflict, or the next read/commit sees a
                    # conflicted working tree.
                    self._git("merge", "--abort", check=False)
                    raise StoreError(
                        f"Merge of {branch} conflicts with main; resolve manually. "
                        f"{result.stdout.strip()} {result.stderr.strip()}".strip()
                    )
                self._git("branch", "-D", branch)
                return self._git("rev-parse", "HEAD").strip()

        async with _async_mutation_lock_for(self.root):
            return await asyncio.to_thread(_merge)

    async def delete_branch(self, branch: str) -> None:
        def _delete():
            with self._lock():
                self._git("branch", "-D", branch)

        async with _async_mutation_lock_for(self.root):
            await asyncio.to_thread(_delete)

    async def push_mirror(self) -> None:
        """Best-effort push to the configured remote mirror."""
        if not settings.context_store_remote:
            return

        def _push():
            self._git("push", "--quiet", settings.context_store_remote, "main", check=False)

        await asyncio.to_thread(_push)
