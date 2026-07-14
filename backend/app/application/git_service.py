"""Async git CLI wrapper.

All git operations shell out to the system `git` binary via
`asyncio.create_subprocess_exec`. Arguments are passed as a list (never
joined into a shell string) and untrusted inputs (branch names, paths)
are validated against a strict character whitelist to prevent command
injection and accidental injection of git options.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TypedDict

from app.domain.models import GitBranch


class GitError(RuntimeError):
    """Raised when a git command fails or input validation rejects an arg."""


# Branch names: standard git ref characters plus a few safe punctuation marks.
# Disallows leading dash so the value can never be interpreted as a flag.
_BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]+$")

# Remote names are narrower than branch names (no slashes).
_REMOTE_RE = re.compile(r"^(?!-)[A-Za-z0-9._-]+$")


def _validate_branch(name: str) -> str:
    if not name or not _BRANCH_RE.fullmatch(name):
        raise GitError(f"invalid branch name: {name!r}")
    return name


def _validate_remote(name: str) -> str:
    if not name or not _REMOTE_RE.fullmatch(name):
        raise GitError(f"invalid remote name: {name!r}")
    return name


def _validate_path(path: str | Path) -> str:
    p = str(path)
    if not p or p.startswith("-"):
        raise GitError(f"invalid path: {p!r}")
    return p


def _validate_url(url: str) -> str:
    # Allow http(s), git, ssh, and scp-style URLs. Reject anything starting with a dash.
    if not url or url.startswith("-"):
        raise GitError(f"invalid url: {url!r}")
    if not re.fullmatch(r"[A-Za-z0-9_@.+/:~%?=&#-]+", url):
        raise GitError(f"invalid url: {url!r}")
    return url


@dataclass
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str


class RemoteGitStatus(TypedDict):
    branch: str
    current_branch: str
    has_origin: bool
    dirty: bool
    behind: int
    ahead: int
    can_fast_forward: bool
    fetched: bool
    error: str | None


class DiffShortstat(TypedDict):
    files: int
    insertions: int
    deletions: int


class GitService:
    """Thin async wrapper around the `git` CLI."""

    def __init__(self, git_binary: str | None = None):
        self._git = git_binary or shutil.which("git") or "git"

    async def _run(
        self,
        args: list[str],
        cwd: str | Path | None = None,
        check: bool = True,
        timeout: float = 60.0,
    ) -> _CommandResult:
        # Force English output and disable interactive prompts so behaviour is deterministic.
        env = {"LANG": "C.UTF-8", "GIT_TERMINAL_PROMPT": "0"}
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            self._git,
            *args,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**__import__("os").environ, **env},
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:  # noqa: UP041
            proc.kill()
            await proc.wait()
            # Audit the timeout (best-effort) before raising.
            self._audit_git(
                args, cwd, None, "", "timeout", started, error=f"timed out after {timeout}s"
            )
            raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from exc
        result = _CommandResult(
            returncode=proc.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
        self._audit_git(args, cwd, result.returncode, result.stdout, result.stderr, started)
        if check and result.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed (rc={result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    @staticmethod
    def _audit_git(
        args: list[str],
        cwd: str | Path | None,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        started: float,
        *,
        error: str | None = None,
    ) -> None:
        """Record one git command into the unified audit_log.

        Thin forwarding shell over `audit.record_git_command` — the payload
        shaping (argv, tail-trim, status derivation) lives in the audit package
        now. Kept as a static method so the hot `_run` path and existing tests
        keep their call site.
        """
        from app.application import audit

        audit.record_git_command(args, cwd, exit_code, stdout, stderr, started, error=error)

    # --- Repo validation ---

    async def is_git_repo(self, path: str | Path) -> bool:
        try:
            await self._run(["rev-parse", "--is-inside-work-tree"], cwd=path)
            return True
        except GitError:
            return False

    # --- Clone ---

    async def clone(self, url: str, dest: str | Path, timeout: float = 600.0) -> str:
        _validate_url(url)
        dest_p = Path(_validate_path(dest))
        if dest_p.exists() and any(dest_p.iterdir()):
            raise GitError(f"clone destination not empty: {dest_p}")
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        await self._run(["clone", "--", url, str(dest_p)], timeout=timeout)
        return str(dest_p)

    # --- Branches ---

    async def default_branch(self, repo_path: str | Path) -> str:
        _validate_path(repo_path)
        # Prefer origin/HEAD if a remote is configured.
        result = await self._run(
            ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
            cwd=repo_path,
            check=False,
        )
        if result.returncode == 0:
            short = result.stdout.strip()
            # symbolic-ref returns e.g. "origin/main" → take the branch name
            if "/" in short:
                return short.split("/", 1)[1]
            return short
        # Fall back to the currently checked-out branch.
        result = await self._run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, check=False)
        if result.returncode == 0:
            return result.stdout.strip() or "main"
        return "main"

    async def list_branches(self, repo_path: str | Path) -> list[GitBranch]:
        _validate_path(repo_path)
        fmt = "%(refname:short)|%(committerdate:iso-strict)|%(objectname)|%(HEAD)"
        result = await self._run(
            [
                "for-each-ref",
                f"--format={fmt}",
                "refs/heads",
                "refs/remotes",
            ],
            cwd=repo_path,
        )
        out: list[GitBranch] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) < 4:
                continue
            name, date_str, sha, head_marker = parts[0], parts[1], parts[2], parts[3]
            # Skip the HEAD pseudo-ref on remotes (e.g. "origin/HEAD").
            if name.endswith("/HEAD"):
                continue
            try:
                commit_date = datetime.fromisoformat(date_str)
            except ValueError:
                commit_date = None
            out.append(
                GitBranch(
                    name=name,
                    is_current=head_marker.strip() == "*",
                    is_remote=name.startswith("origin/")
                    or "/" in name  # noqa: RUF021
                    and not name.startswith("refs/"),  # noqa: RUF021, RUF100
                    last_commit_date=commit_date,
                    last_commit_sha=sha or None,
                )
            )
        # Most recent first.
        out.sort(key=lambda b: b.last_commit_date or datetime.min, reverse=True)
        return out

    # --- Remote sync ---

    async def has_remote(self, repo_path: str | Path, remote: str = "origin") -> bool:
        """Return True iff `remote` is configured on the repo."""
        _validate_path(repo_path)
        if not _REMOTE_RE.fullmatch(remote):
            return False
        result = await self._run(["remote"], cwd=repo_path, check=False)
        return remote in result.stdout.split()

    async def current_branch(self, repo_path: str | Path) -> str:
        """Return the currently checked-out branch name (empty if detached)."""
        _validate_path(repo_path)
        result = await self._run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, check=False)
        name = result.stdout.strip()
        # Detached HEAD reports "HEAD"; treat as no branch.
        return "" if name == "HEAD" else name

    async def _ref_exists(self, repo_path: str | Path, ref: str) -> bool:
        result = await self._run(
            ["show-ref", "--verify", "--quiet", ref],
            cwd=repo_path,
            check=False,
        )
        return result.returncode == 0

    async def _count_range(self, repo_path: str | Path, range_expr: str) -> int:
        result = await self._run(
            ["rev-list", "--count", range_expr],
            cwd=repo_path,
            check=False,
        )
        try:
            return int(result.stdout.strip() or "0")
        except ValueError:
            return 0

    async def fetch(
        self,
        repo_path: str | Path,
        remote: str = "origin",
        branch: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        """`git fetch` to update remote-tracking refs. Raises GitError on failure
        (e.g. no network / auth). Never touches the working tree."""
        _validate_path(repo_path)
        _validate_remote(remote)
        args = ["fetch", "--quiet", remote]
        if branch is not None:
            _validate_branch(branch)
            args.append(branch)
        await self._run(args, cwd=repo_path, timeout=timeout)

    async def fast_forward(
        self,
        repo_path: str | Path,
        branch: str,
        remote: str = "origin",
    ) -> str:
        """Fast-forward the repo's checked-out branch to `<remote>/<branch>`.

        Uses `merge --ff-only` (NO autostash): if the merge cannot be a clean
        fast-forward — diverged history, or local edits that would be
        overwritten — git refuses and the working tree is left exactly as it
        was. Raises GitError in that case. Returns the new HEAD SHA on success.
        Callers must pre-check that the repo is on `branch` and clean.
        """
        _validate_path(repo_path)
        _validate_branch(branch)
        _validate_remote(remote)
        result = await self._run(
            ["merge", "--ff-only", f"{remote}/{branch}"],
            cwd=repo_path,
            check=False,
        )
        if result.returncode != 0:
            raise GitError(f"fast-forward failed: {result.stderr.strip() or result.stdout.strip()}")
        head = await self._run(["rev-parse", "HEAD"], cwd=repo_path)
        return head.stdout.strip()

    async def remote_status(
        self,
        repo_path: str | Path,
        branch: str | None = None,
        remote: str = "origin",
        do_fetch: bool = True,
    ) -> RemoteGitStatus:
        """Compute how the local default branch relates to its remote.

        Returns a dict shaped for the API/UI:
          - branch:          the default branch we compare (resolved if not given)
          - current_branch:  what the repo currently has checked out
          - has_origin:      whether `remote` is configured
          - dirty:           working tree has uncommitted changes
          - behind / ahead:  commit counts of local `branch` vs `<remote>/<branch>`
          - can_fast_forward: safe to one-click pull (on default, clean, behind>0, ahead==0)
          - fetched:         whether a fetch actually ran and succeeded
          - error:           machine reason when status is degraded, else None
                             (not_a_git_repo / no_origin / fetch_failed / no_remote_branch)

        Never raises for the common failure modes — they surface via `error`.
        """
        _validate_path(repo_path)
        if not await self.is_git_repo(repo_path):
            return {
                "branch": branch or "",
                "current_branch": "",
                "has_origin": False,
                "dirty": False,
                "behind": 0,
                "ahead": 0,
                "can_fast_forward": False,
                "fetched": False,
                "error": "not_a_git_repo",
            }

        has_origin = await self.has_remote(repo_path, remote)
        branch = _validate_branch(branch or await self.default_branch(repo_path))

        error: str | None = None
        fetched = False
        if not has_origin:
            error = "no_origin"
        elif do_fetch:
            try:
                await self.fetch(repo_path, remote=remote, branch=branch)
                fetched = True
            except GitError:
                error = "fetch_failed"

        current_branch = await self.current_branch(repo_path)
        dirty = bool((await self.status_porcelain(repo_path)).strip())

        behind = ahead = 0
        remote_ref = f"{remote}/{branch}"
        remote_ref_exists = has_origin and await self._ref_exists(
            repo_path, f"refs/remotes/{remote_ref}"
        )
        local_ref_exists = await self._ref_exists(repo_path, f"refs/heads/{branch}")
        if remote_ref_exists and local_ref_exists:
            behind = await self._count_range(repo_path, f"{branch}..{remote_ref}")
            ahead = await self._count_range(repo_path, f"{remote_ref}..{branch}")
        elif has_origin and not remote_ref_exists and error is None:
            error = "no_remote_branch"

        can_fast_forward = (
            has_origin
            and error is None
            and not dirty
            and current_branch == branch
            and ahead == 0
            and behind > 0
        )
        return {
            "branch": branch,
            "current_branch": current_branch,
            "has_origin": has_origin,
            "dirty": dirty,
            "behind": behind,
            "ahead": ahead,
            "can_fast_forward": can_fast_forward,
            "fetched": fetched,
            "error": error,
        }

    # --- Worktrees ---

    async def create_worktree(
        self,
        repo_path: str | Path,
        branch: str,
        worktree_path: str | Path,
        base_branch: str,
    ) -> None:
        _validate_path(repo_path)
        _validate_path(worktree_path)
        _validate_branch(branch)
        _validate_branch(base_branch)
        worktree_p = Path(worktree_path)
        worktree_p.parent.mkdir(parents=True, exist_ok=True)
        # Prune dangling worktree metadata so a stale entry can't block creation.
        await self._run(["worktree", "prune"], cwd=repo_path, check=False)
        # Use -B (force create/reset the branch to base) rather than -b: a prior
        # run can leave the issue/agent branch behind (cleanup removes the
        # worktree but not the ref), and -b would then fail with "branch already
        # exists", silently aborting worktree creation. -B is idempotent — the
        # branch is freshly reset to base, which is exactly what a new worktree
        # wants. Safe here because we only create when no live worktree holds it.
        await self._run(
            [
                "worktree",
                "add",
                "-B",
                branch,
                str(worktree_p),
                base_branch,
            ],
            cwd=repo_path,
        )

    async def remove_worktree(self, repo_path: str | Path, worktree_path: str | Path) -> None:
        _validate_path(repo_path)
        _validate_path(worktree_path)
        # Best-effort remove (--force handles a dirty worktree). Ignore failure
        # so we can still clean up the directory below.
        await self._run(
            ["worktree", "remove", "--force", str(worktree_path)],
            cwd=repo_path,
            check=False,
        )
        await self._run(["worktree", "prune"], cwd=repo_path, check=False)

    # --- Squash merge ---

    async def squash_merge(
        self,
        repo_path: str | Path,
        source_branch: str,
        base_branch: str,
        message: str,
    ) -> str:
        """Squash-merge `source_branch` into `base_branch`.

        Uses a temporary worktree so the primary repo's working tree is never
        touched — the merge succeeds even when the primary repo has local edits.

        Returns the new commit SHA on `base_branch`.
        """
        _validate_path(repo_path)
        _validate_branch(source_branch)
        _validate_branch(base_branch)
        if not message.strip():
            raise GitError("merge message must not be empty")

        repo_p = Path(repo_path)
        # Place the temp worktree alongside the existing worktrees directory.
        tmp_path = repo_p.parent / f".jm-merge-{source_branch[:24].replace('/', '-')}"

        # Prune stale metadata first so a leftover entry can't block creation.
        await self._run(["worktree", "prune"], cwd=repo_p, check=False)
        # Remove any leftover directory from a previous failed merge.
        if tmp_path.exists():
            await self._run(
                ["worktree", "remove", "--force", str(tmp_path)], cwd=repo_p, check=False
            )
            import shutil as _shutil

            if tmp_path.exists():
                _shutil.rmtree(tmp_path, ignore_errors=True)

        # --detach checks out the commit rather than the branch ref, so it
        # never conflicts with the primary repo already having base_branch checked out.
        await self._run(
            ["worktree", "add", "--detach", str(tmp_path), base_branch],
            cwd=repo_p,
        )
        try:
            merge_result = await self._run(
                ["merge", "--squash", "--", source_branch],
                cwd=tmp_path,
                check=False,
            )
            if merge_result.returncode != 0:
                await self._run(["reset", "--hard", "HEAD"], cwd=tmp_path, check=False)
                raise GitError(
                    f"squash merge failed: {merge_result.stderr.strip() or merge_result.stdout.strip()}"
                )
            commit_result = await self._run(
                ["commit", "-m", message],
                cwd=tmp_path,
                check=False,
            )
            if commit_result.returncode != 0:
                await self._run(["reset", "--hard", "HEAD"], cwd=tmp_path, check=False)
                raise GitError(
                    f"squash commit failed: {commit_result.stderr.strip() or commit_result.stdout.strip()}"
                )
            head = await self._run(["rev-parse", "HEAD"], cwd=tmp_path)
            new_sha = head.stdout.strip()
            # Fast-forward the primary repo to the squash commit.
            # --autostash stashes local edits, applies ff-merge (which advances
            # refs/heads/<base_branch> and updates working tree), then pops the
            # stash.  This is best-effort; if it fails the git history is still
            # correct — callers can git pull/reset manually.
            await self._run(
                ["merge", "--ff-only", "--autostash", new_sha],
                cwd=repo_p,
                check=False,
            )
            # If primary repo HEAD didn't move (e.g. autostash pop had conflicts
            # and the merge was rolled back), advance the ref directly so at
            # minimum the branch pointer is correct.
            current_head = await self._run(["rev-parse", "HEAD"], cwd=repo_p, check=False)
            if current_head.stdout.strip() != new_sha:
                await self._run(
                    ["update-ref", f"refs/heads/{base_branch}", new_sha],
                    cwd=repo_p,
                    check=False,
                )
            return new_sha
        finally:
            await self._run(
                ["worktree", "remove", "--force", str(tmp_path)],
                cwd=repo_p,
                check=False,
            )
            await self._run(["worktree", "prune"], cwd=repo_p, check=False)

    async def squash_merge_into_branch(
        self,
        repo_path: str | Path,
        source_branch: str,
        target_branch: str,
        message: str,
        target_worktree_path: str | Path | None = None,
    ) -> str:
        """Squash-merge `source_branch` into `target_branch` WITHOUT touching the
        primary repo's checked-out branch.

        Unlike :meth:`squash_merge`, this never runs a fast-forward in the
        primary repo. That matters for the swarm merge-back: the swarm target
        (the issue integration branch) is *not* checked out in the primary repo
        — the primary repo is usually on the project default branch (e.g.
        ``main``). Because the issue branch descends from the default branch,
        the default branch IS an ancestor of the squash commit, so a
        ``merge --ff-only`` in the primary repo would happily fast-forward the
        DEFAULT branch onto unreviewed agent changes, polluting it and bypassing
        the normal ``merge_issue`` review flow.

        Instead this:

        1. squash-merges in a throwaway detached worktree at ``target_branch``'s
           tip (conflicts ``reset --hard`` + raise ``GitError``, no half state),
        2. advances ``refs/heads/<target_branch>`` to the squash commit via
           ``update-ref`` (the only branch ref touched),
        3. if ``target_worktree_path`` is provided and that worktree has
           ``target_branch`` checked out, syncs its index/working tree to the
           new commit with ``reset --hard`` so the worktree doesn't go stale
           under a moved branch ref.

        Returns the new commit SHA on ``target_branch``.
        """
        _validate_path(repo_path)
        _validate_branch(source_branch)
        _validate_branch(target_branch)
        if not message.strip():
            raise GitError("merge message must not be empty")

        repo_p = Path(repo_path)
        tmp_path = repo_p.parent / f".jm-swarm-merge-{source_branch[:24].replace('/', '-')}"

        await self._run(["worktree", "prune"], cwd=repo_p, check=False)
        if tmp_path.exists():
            await self._run(
                ["worktree", "remove", "--force", str(tmp_path)], cwd=repo_p, check=False
            )
            if tmp_path.exists():
                shutil.rmtree(tmp_path, ignore_errors=True)

        # Detach at the target branch tip so we never hold the branch ref (the
        # target worktree may already have it checked out).
        await self._run(
            ["worktree", "add", "--detach", str(tmp_path), target_branch],
            cwd=repo_p,
        )
        try:
            merge_result = await self._run(
                ["merge", "--squash", "--", source_branch],
                cwd=tmp_path,
                check=False,
            )
            if merge_result.returncode != 0:
                await self._run(["reset", "--hard", "HEAD"], cwd=tmp_path, check=False)
                raise GitError(
                    f"squash merge failed: {merge_result.stderr.strip() or merge_result.stdout.strip()}"
                )
            commit_result = await self._run(
                ["commit", "-m", message],
                cwd=tmp_path,
                check=False,
            )
            if commit_result.returncode != 0:
                await self._run(["reset", "--hard", "HEAD"], cwd=tmp_path, check=False)
                raise GitError(
                    f"squash commit failed: {commit_result.stderr.strip() or commit_result.stdout.strip()}"
                )
            head = await self._run(["rev-parse", "HEAD"], cwd=tmp_path)
            new_sha = head.stdout.strip()
            # Advance ONLY the target branch ref. Primary repo's checked-out
            # branch (default) is never touched.
            await self._run(
                ["update-ref", f"refs/heads/{target_branch}", new_sha],
                cwd=repo_p,
                check=False,
            )
            # Keep the target worktree consistent with the moved ref. We only
            # reset when that worktree actually has target_branch checked out;
            # otherwise the ref move doesn't concern it.
            if target_worktree_path is not None:
                _validate_path(target_worktree_path)
                current = await self._run(
                    ["rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=target_worktree_path,
                    check=False,
                )
                if current.stdout.strip() == target_branch:
                    await self._run(
                        ["reset", "--hard", new_sha],
                        cwd=target_worktree_path,
                        check=False,
                    )
            return new_sha
        finally:
            await self._run(
                ["worktree", "remove", "--force", str(tmp_path)],
                cwd=repo_p,
                check=False,
            )
            await self._run(["worktree", "prune"], cwd=repo_p, check=False)

    # --- Diff / inspection ---

    async def worktree_diff(self, worktree_path: str | Path, base_branch: str) -> str:
        _validate_path(worktree_path)
        _validate_branch(base_branch)
        # Show both committed and working-directory changes vs base.
        # This lets diff view work even when the agent hasn't committed yet.
        tracked = await self._run(
            ["diff", base_branch],
            cwd=worktree_path,
            check=False,
        )
        # Append synthetic patch entries for untracked new files.
        untracked = await self._run(
            ["ls-files", "--others", "--exclude-standard"],
            cwd=worktree_path,
            check=False,
        )
        parts = [tracked.stdout]
        for rel_path in untracked.stdout.splitlines():
            rel_path = rel_path.strip()
            if not rel_path:
                continue
            try:
                content = (Path(worktree_path) / rel_path).read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                continue
            lines = content.splitlines(keepends=True)
            added = "".join(f"+{l}" if l.endswith("\n") else f"+{l}\n" for l in lines)  # noqa: E741
            parts.append(
                f"diff --git a/{rel_path} b/{rel_path}\n"
                f"new file mode 100644\n"
                f"--- /dev/null\n"
                f"+++ b/{rel_path}\n"
                f"@@ -0,0 +1,{len(lines)} @@\n"
                f"{added}"
            )
        return "".join(parts)

    async def head_commit(self, worktree_path: str | Path) -> str:
        _validate_path(worktree_path)
        result = await self._run(["rev-parse", "HEAD"], cwd=worktree_path)
        return result.stdout.strip()

    async def working_tree_snapshot_revision(self, repo_path: str | Path) -> str:
        """Create a detached revision for the current tracked working tree.

        ``git stash create`` writes a commit object without updating refs, the
        index, or the working tree. It therefore gives an isolated worktree the
        exact staged + unstaged tracked source visible to evidence scanning
        without stashing or committing the user's changes.
        """
        _validate_path(repo_path)
        result = await self._run(
            ["stash", "create", "prototype generation source snapshot"],
            cwd=repo_path,
            check=False,
        )
        if result.returncode != 0:
            raise GitError(
                "could not snapshot project working tree: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        revision = result.stdout.strip()
        return revision or await self.head_commit(repo_path)

    async def repository_prefix(self, repo_path: str | Path) -> str:
        """Return the project path relative to the containing Git worktree root."""
        _validate_path(repo_path)
        result = await self._run(["rev-parse", "--show-prefix"], cwd=repo_path)
        prefix = result.stdout.strip().rstrip("/")
        relative = Path(prefix)
        if relative.is_absolute() or ".." in relative.parts:
            raise GitError("git returned an unsafe repository prefix")
        return relative.as_posix() if prefix else ""

    async def initialize_snapshot_repository(self, repo_path: str | Path) -> str:
        """Create a standalone baseline repository for an isolated nested project."""
        _validate_path(repo_path)
        await self._run(["init", "-b", "prototype-snapshot"], cwd=repo_path)
        await self._run(["add", "--all", "--", "."], cwd=repo_path)
        await self._run(
            [
                "-c",
                "user.name=Agent Collab",
                "-c",
                "user.email=agent-collab@localhost",
                "commit",
                "--allow-empty",
                "-m",
                "prototype source snapshot",
            ],
            cwd=repo_path,
        )
        return await self.head_commit(repo_path)

    async def list_untracked_files(self, repo_path: str | Path) -> list[str]:
        """List non-ignored untracked files using NUL-delimited git output."""
        _validate_path(repo_path)
        result = await self._run(
            ["ls-files", "--others", "--exclude-standard", "-z", "--", "."],
            cwd=repo_path,
        )
        return [path for path in result.stdout.split("\0") if path]

    async def status_porcelain(self, worktree_path: str | Path) -> str:
        """Return `git status --porcelain` output (empty string == clean tree)."""
        _validate_path(worktree_path)
        result = await self._run(["status", "--porcelain"], cwd=worktree_path)
        return result.stdout

    async def commit_all(self, worktree_path: str | Path, message: str) -> str | None:
        """Stage every change (tracked + untracked) and commit.

        Returns the new HEAD SHA, or None if there was nothing to commit.
        """
        _validate_path(worktree_path)
        if not message.strip():
            raise GitError("commit message must not be empty")
        await self._run(["add", "-A"], cwd=worktree_path)
        result = await self._run(["commit", "-m", message], cwd=worktree_path, check=False)
        if result.returncode != 0:
            # "nothing to commit" is not a real error.
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                return None
            raise GitError(f"git commit failed: {result.stderr.strip() or result.stdout.strip()}")
        head = await self._run(["rev-parse", "HEAD"], cwd=worktree_path)
        return head.stdout.strip()

    async def branch_exists(self, repo_path: str | Path, branch: str) -> bool:
        """Return True iff `branch` is currently a local ref on the repo."""
        _validate_path(repo_path)
        if not _BRANCH_RE.fullmatch(branch):
            return False
        result = await self._run(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=repo_path,
            check=False,
        )
        return result.returncode == 0

    async def commits_ahead(self, worktree_path: str | Path, base_branch: str) -> int:
        """Number of commits on the worktree's HEAD that aren't on `base_branch`."""
        _validate_path(worktree_path)
        _validate_branch(base_branch)
        result = await self._run(
            ["rev-list", "--count", f"{base_branch}..HEAD"],
            cwd=worktree_path,
            check=False,
        )
        try:
            return int(result.stdout.strip() or "0")
        except ValueError:
            return 0

    async def commits_behind(self, worktree_path: str | Path, base_branch: str) -> int:
        """How many commits the base branch has gained that the worktree HEAD lacks."""
        _validate_path(worktree_path)
        _validate_branch(base_branch)
        result = await self._run(
            ["rev-list", "--count", f"HEAD..{base_branch}"],
            cwd=worktree_path,
            check=False,
        )
        try:
            return int(result.stdout.strip() or "0")
        except ValueError:
            return 0

    async def diff_shortstat(self, worktree_path: str | Path, base_branch: str) -> DiffShortstat:
        """Return a compact summary `{files, insertions, deletions}` vs base.

        Uses `git diff --shortstat <base>...HEAD` then parses the standard line:
        "N files changed, K insertions(+), M deletions(-)" — any of the three
        clauses may be missing.
        """
        _validate_path(worktree_path)
        _validate_branch(base_branch)
        result = await self._run(
            ["diff", "--shortstat", base_branch],
            cwd=worktree_path,
            check=False,
        )
        out: DiffShortstat = {"files": 0, "insertions": 0, "deletions": 0}
        text = result.stdout.strip()
        if not text:
            return out
        import re as _re

        patterns: tuple[
            tuple[str, Literal["files", "insertions", "deletions"]],
            ...,
        ] = (
            (r"(\d+) files? changed", "files"),
            (r"(\d+) insertions?", "insertions"),
            (r"(\d+) deletions?", "deletions"),
        )
        for clause, key in patterns:
            m = _re.search(clause, text)
            if m:
                out[key] = int(m.group(1))
        return out

    async def conflicted_files(self, worktree_path: str | Path) -> list[str]:
        """Return the list of files currently in merge-conflict state.

        Runs `git diff --name-only --diff-filter=U` in the worktree. This is the
        input the swarm reconcile flow feeds to the Conductor when a per-agent
        squash-merge back into the issue branch fails (see vibe-kanban
        `get_conflicted_files`). Returns an empty list when there are no
        unmerged paths.
        """
        _validate_path(worktree_path)
        result = await self._run(
            ["diff", "--name-only", "--diff-filter=U"],
            cwd=worktree_path,
            check=False,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    async def prune_worktrees(self, repo_path: str | Path) -> None:
        _validate_path(repo_path)
        await self._run(["worktree", "prune"], cwd=repo_path, check=False)

    async def list_worktree_paths(self, repo_path: str | Path) -> list[str]:
        _validate_path(repo_path)
        result = await self._run(["worktree", "list", "--porcelain"], cwd=repo_path, check=False)
        out: list[str] = []
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                out.append(line[len("worktree ") :].strip())
        return out

    async def list_branch_names(self, repo_path: str | Path, prefix: str) -> list[str]:
        """Return local branch names matching `<prefix>*` (refs/heads only).

        Used to discover residual swarm branches for terminal cleanup without
        relying on in-memory lineage (which is not persisted). `prefix` is a
        literal branch-name prefix; the trailing `*` glob is appended here.
        """
        _validate_path(repo_path)
        if not prefix or not _BRANCH_RE.fullmatch(prefix):
            return []
        result = await self._run(
            ["branch", "--list", "--format=%(refname:short)", f"{prefix}*"],
            cwd=repo_path,
            check=False,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    async def delete_branch(self, repo_path: str | Path, branch: str) -> None:
        """Force-delete a local branch ref (`git branch -D`). Idempotent: a
        missing branch is ignored. Only touches `refs/heads/<branch>`; never
        checks out or rewrites any other ref, so the primary repo's HEAD is
        untouched."""
        _validate_path(repo_path)
        if not branch or not _BRANCH_RE.fullmatch(branch):
            return
        await self._run(["branch", "-D", branch], cwd=repo_path, check=False)


git_service = GitService()
