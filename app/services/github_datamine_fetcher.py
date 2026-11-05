"""
CS2 Instant Alert — GitHub Datamine Fetcher.

Fetches git diffs and version details from SteamTracking/GameTracking-CS2.
Applies smart filtering to extract convars, script API (.d.ts), Panorama UI,
and resource strings while strictly capping token usage for LLM analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger("system")

# Priority groups for file pattern filtering
# Patterns in lower index have higher inclusion priority
PRIORITY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("convars", re.compile(r"^DumpSource2/(convars|commands)\.txt$", re.IGNORECASE)),
    ("configs", re.compile(r".*/cfg/.*\.cfg$", re.IGNORECASE)),
    ("scripts", re.compile(r".*/scripts/.*(whitelist|cvar|items|weapon|script).*\.txt$", re.IGNORECASE)),
    ("items", re.compile(r".*/items/items_game.*\.txt$", re.IGNORECASE)),
    ("scripting", re.compile(r".*\.d\.ts$", re.IGNORECASE)),
    ("panorama", re.compile(r".*/panorama/(styles|layout|scripts)/.*", re.IGNORECASE)),
    ("resource", re.compile(r".*/resource/csgo_(english|russian)\.txt$", re.IGNORECASE)),
    ("vdata", re.compile(r".*/scripts/.*\.vdata$", re.IGNORECASE)),
    ("asset_info", re.compile(r".*readonly_tools_asset_info\.txt$", re.IGNORECASE)),
    ("soundstacks", re.compile(r".*/soundstacks/.*\.vsndstck$", re.IGNORECASE)),
    ("strings", re.compile(r".*_strings\.txt$", re.IGNORECASE)),
    ("soundevents", re.compile(r".*/soundevents/.*\.vsndevts$", re.IGNORECASE)),
    ("protobufs", re.compile(r"^Protobufs/.*", re.IGNORECASE)),
]


@dataclass
class GitHubDatamineResult:
    """Structured result of GitHub datamining."""

    commit_sha: str
    commit_url: str
    commit_date: datetime
    patch_version: str | None = None
    client_version: str | None = None
    server_version: str | None = None
    filtered_diff: str = ""
    matched_files: list[str] = field(default_factory=list)
    has_relevant_changes: bool = False


class GitHubDatamineFetcher:
    """Fetches and processes commits from SteamTracking/GameTracking-CS2."""

    REPO_URL = "https://api.github.com/repos/SteamTracking/GameTracking-CS2"

    def __init__(
        self,
        github_token: str | None = None,
        timeout_seconds: float = 15.0,
        max_diff_chars: int = 45000,
    ) -> None:
        if github_token is not None and hasattr(github_token, "get_secret_value"):
            github_token = github_token.get_secret_value()
        self.github_token = github_token
        self.timeout_seconds = timeout_seconds
        self.max_diff_chars = max_diff_chars

    def _get_headers(self, anonymous: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "CS2-Instant-Alert-Bot/1.0",
        }
        if not anonymous and self.github_token and str(self.github_token).strip():
            headers["Authorization"] = f"Bearer {str(self.github_token).strip()}"
        return headers

    async def fetch_matching_commit(
        self,
        detected_at: datetime,
        min_window_minutes_before: int = 10,
    ) -> GitHubDatamineResult | None:
        """
        Check for a commit in GameTracking-CS2 matching the update timeframe.

        Returns:
            GitHubDatamineResult with parsed steam.inf version and filtered diffs,
            or None if no matching commit found yet.
        """
        list_url = f"{self.REPO_URL}/commits?per_page=5"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get(list_url, headers=self._get_headers())

                if resp.status_code == 401 and self.github_token:
                    await logger.awarning("github_token_unauthorized_falling_back_anonymous")
                    resp = await client.get(list_url, headers=self._get_headers(anonymous=True))

                if resp.status_code == 403:
                    await logger.awarning("github_rate_limited", status=403)
                    return None

                if resp.status_code != 200:
                    await logger.awarning(
                        "github_commits_fetch_failed",
                        status_code=resp.status_code,
                    )
                    return None

                commits = resp.json()
                if not isinstance(commits, list) or not commits:
                    return None

                window_start = detected_at - timedelta(minutes=min_window_minutes_before)

                target_commit = None
                for c in commits:
                    date_str = (
                        c.get("commit", {})
                        .get("committer", {})
                        .get("date")
                    )
                    if not date_str:
                        continue

                    # GitHub dates are in ISO 8601 (e.g., 2026-10-22T22:56:41Z)
                    commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))

                    if commit_date >= window_start:
                        target_commit = c
                        break

                if not target_commit:
                    return None

                sha = target_commit["sha"]
                commit_html_url = target_commit.get("html_url", f"https://github.com/SteamTracking/GameTracking-CS2/commit/{sha}")
                commit_date_str = target_commit.get("commit", {}).get("committer", {}).get("date", "")
                commit_dt = (
                    datetime.fromisoformat(commit_date_str.replace("Z", "+00:00"))
                    if commit_date_str
                    else datetime.now(UTC)
                )

                # Fetch full commit details including files diff
                detail_url = f"{self.REPO_URL}/commits/{sha}"
                detail_resp = await client.get(detail_url, headers=self._get_headers())

                if detail_resp.status_code == 401 and self.github_token:
                    await logger.awarning("github_token_unauthorized_detail_falling_back_anonymous")
                    detail_resp = await client.get(detail_url, headers=self._get_headers(anonymous=True))

                if detail_resp.status_code != 200:
                    await logger.awarning("github_commit_detail_failed", sha=sha, status=detail_resp.status_code)
                    return None

                detail_data = detail_resp.json()
                files = detail_data.get("files", [])

                return self._parse_commit_data(sha, commit_html_url, commit_dt, files)

        except httpx.TimeoutException:
            await logger.awarning("github_datamine_timeout")
        except Exception as e:
            await logger.aerror("github_datamine_error", error=str(e), exc_info=True)

        return None

    def _parse_commit_data(
        self,
        sha: str,
        commit_url: str,
        commit_dt: datetime,
        files: list[dict[str, Any]],
    ) -> GitHubDatamineResult:
        """Parse files from commit: extract steam.inf version and filter diffs."""
        patch_version: str | None = None
        client_version: str | None = None
        server_version: str | None = None

        # 1. Parse steam.inf
        for f in files:
            filename = f.get("filename", "")
            if filename.endswith("steam.inf"):
                patch_content = f.get("patch", "")
                patch_ver_match = re.search(r"^\+PatchVersion=([0-9.]+)", patch_content, re.MULTILINE)
                if patch_ver_match:
                    patch_version = patch_ver_match.group(1).strip()

                client_ver_match = re.search(r"^\+ClientVersion=([0-9.]+)", patch_content, re.MULTILINE)
                if client_ver_match:
                    client_version = client_ver_match.group(1).strip()

                server_ver_match = re.search(r"^\+ServerVersion=([0-9.]+)", patch_content, re.MULTILINE)
                if server_ver_match:
                    server_version = server_ver_match.group(1).strip()
                break

        # 2. Group files by priority
        prioritized_files: list[list[tuple[str, str]]] = [[] for _ in PRIORITY_PATTERNS]
        matched_filenames: list[str] = []

        for f in files:
            filename = f.get("filename", "")
            patch = f.get("patch", "")
            if not patch:
                continue

            for idx, (_, pattern) in enumerate(PRIORITY_PATTERNS):
                if pattern.match(filename):
                    prioritized_files[idx].append((filename, patch))
                    matched_filenames.append(filename)
                    break

        # 3. Assemble filtered diff up to self.max_diff_chars
        diff_chunks: list[str] = []
        current_len = 0
        has_relevant = False

        group_limits = {"soundevents": 6, "strings": 6}

        for idx, group in enumerate(prioritized_files):
            group_name = PRIORITY_PATTERNS[idx][0]
            limit = group_limits.get(group_name, len(group))
            files_to_process = group[:limit]
            skipped_count = len(group) - limit

            for filename, patch in files_to_process:
                has_relevant = True
                chunk_header = f"--- a/{filename}\n+++ b/{filename}\n"
                chunk_budget = self.max_diff_chars - current_len - len(chunk_header)

                if chunk_budget <= 200:
                    # Budget exhausted
                    break

                if len(patch) > chunk_budget:
                    # Truncate large single file diff
                    truncated_patch = patch[:chunk_budget] + "\n... [diff truncated]"
                    diff_chunks.append(chunk_header + truncated_patch)
                    current_len += len(chunk_header) + len(truncated_patch)
                    break
                else:
                    diff_chunks.append(chunk_header + patch)
                    current_len += len(chunk_header) + len(patch)

            if skipped_count > 0:
                summary_line = f"# ... и ещё {skipped_count} аналогичных файлов {group_name}\n"
                diff_chunks.append(summary_line)
                current_len += len(summary_line)

        assembled_diff = "\n\n".join(diff_chunks)

        logger.info(
            "github_datamine_parsed",
            sha=sha[:8],
            patch_version=patch_version,
            client_version=client_version,
            matched_files_count=len(matched_filenames),
            diff_chars=len(assembled_diff),
        )

        return GitHubDatamineResult(
            commit_sha=sha,
            commit_url=commit_url,
            commit_date=commit_dt,
            patch_version=patch_version,
            client_version=client_version,
            server_version=server_version,
            filtered_diff=assembled_diff,
            matched_files=matched_filenames,
            has_relevant_changes=has_relevant,
        )
