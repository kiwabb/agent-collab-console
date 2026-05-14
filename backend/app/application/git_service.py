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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.domain.models import GitBranch


class GitError(RuntimeError):
    """Raised when a git command fails or input validation rejects an arg."""


# Branch names: standard git ref characters plus a few safe punctuation marks.
# Disallows leading dash so the value can never be interpreted as a flag.
_BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]+$")


def _validate_branch(name: str) -> str:
    if not name or not _BRANCH_RE.fullmatch(name):
        raise GitError(f"invalid branch name: {name!r}")
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
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from exc
        result = _CommandResult(
            returncode=proc.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
        if check and result.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed (rc={result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
            )
        return result

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
                    is_remote=name.startswith("origin/") or "/" in name and not name.startswith("refs/"),
                    last_commit_date=commit_date,
                    last_commit_sha=sha or None,
                )
            )
        # Most recent first.
        out.sort(key=lambda b: b.last_commit_date or datetime.min, reverse=True)
        return out

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
        await self._run(
            [
                "worktree",
                "add",
                "-b",
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
            await self._run(["worktree", "remove", "--force", str(tmp_path)], cwd=repo_p, check=False)
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
                content = (Path(worktree_path) / rel_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = content.splitlines(keepends=True)
            added = "".join(f"+{l}" if l.endswith("\n") else f"+{l}\n" for l in lines)
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

    async def diff_shortstat(self, worktree_path: str | Path, base_branch: str) -> dict:
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
        out = {"files": 0, "insertions": 0, "deletions": 0}
        text = result.stdout.strip()
        if not text:
            return out
        import re as _re
        for clause, key in (
            (r"(\d+) files? changed", "files"),
            (r"(\d+) insertions?", "insertions"),
            (r"(\d+) deletions?", "deletions"),
        ):
            m = _re.search(clause, text)
            if m:
                out[key] = int(m.group(1))
        return out

    async def prune_worktrees(self, repo_path: str | Path) -> None:
        _validate_path(repo_path)
        await self._run(["worktree", "prune"], cwd=repo_path, check=False)

    async def list_worktree_paths(self, repo_path: str | Path) -> list[str]:
        _validate_path(repo_path)
        result = await self._run(["worktree", "list", "--porcelain"], cwd=repo_path, check=False)
        out: list[str] = []
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                out.append(line[len("worktree "):].strip())
        return out


git_service = GitService()
