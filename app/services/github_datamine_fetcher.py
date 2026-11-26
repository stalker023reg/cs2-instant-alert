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
# Covers all game files: balance, configs, items, localization, particles, sounds, maps, UI, animations
PRIORITY_PATTERNS: list[tuple[str, re.Pattern]] = [
    # 1. Gameplay, balance, convars, and configs
    ("convars", re.compile(r"^DumpSource2/(convars|commands)\.txt$", re.IGNORECASE)),
    ("configs", re.compile(r".*(cfg/.*(\.cfg|\.txt)|gameinfo\.gi)$", re.IGNORECASE)),
    ("items", re.compile(r".*(items/items_game.*\.txt|items_event.*\.js|items_game_cdn\.txt)$", re.IGNORECASE)),
    ("resource", re.compile(r".*resource/csgo_(english|russian)\.txt$", re.IGNORECASE)),
    ("scripts", re.compile(r".*(scripts/.*|vdata/.*|\.(txt|kv3|vdata|lua|py))$", re.IGNORECASE)),
    
    # 2. Visuals, Audio, Maps, UI and Animations
    ("particles", re.compile(r".*(particles/.*|\.vpcf.*)", re.IGNORECASE)),
    ("soundevents", re.compile(r".*(soundevents/.*|soundstacks/.*|\.vsndevts|\.vsndstck)", re.IGNORECASE)),
    ("maps", re.compile(r".*maps/.*", re.IGNORECASE)),
    ("panorama", re.compile(r".*panorama/.*", re.IGNORECASE)),
    ("physics", re.compile(r".*(\.vphys.*|physics/.*)", re.IGNORECASE)),
    ("animations", re.compile(r".*(anims/.*|animation/.*|\.vnmclip|\.vanim|\.vnmgraph)", re.IGNORECASE)),
    ("models_materials", re.compile(r".*(models/.*|materials/.*|\.vmdl|\.vmat|\.vtex)", re.IGNORECASE)),

    # 3. Technical, dev tools, schemas
    ("scripting", re.compile(r".*\.d\.ts$", re.IGNORECASE)),
    ("schemas", re.compile(r"^DumpSource2/schemas/.*\.h$", re.IGNORECASE)),
    ("fgd", re.compile(r".*\.fgd$", re.IGNORECASE)),
    ("strings", re.compile(r".*_strings\.txt$", re.IGNORECASE)),
    ("protobufs", re.compile(r"^Protobufs/.*", re.IGNORECASE)),
    ("asset_info", re.compile(r".*readonly_tools_asset_info\.txt$", re.IGNORECASE)),
    
    # 4. Catch-all: ANY other modified game file inside game/content/DumpSource2/Protobufs is NEVER dropped!
    ("other_game_files", re.compile(r"^(game/|content/|DumpSource2/|Protobufs/).*", re.IGNORECASE)),
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
        max_diff_chars: int = 850000,
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
        list_url = f"{self.REPO_URL}/commits?per_page=10"

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

                # In GitHub REST API, commits with >= 300 files truncate the 'files' array.
                # When truncated, alphabetically later files (like game/csgo/pak01_dir.txt and game/csgo/steam.inf)
                # are omitted from the JSON response. For large multi-gigabyte updates, fetch the full raw unified git diff!
                if len(files) >= 300:
                    try:
                        diff_headers = self._get_headers()
                        diff_headers["Accept"] = "application/vnd.github.v3.diff"
                        diff_resp = await client.get(detail_url, headers=diff_headers)
                        if diff_resp.status_code == 200 and diff_resp.text:
                            parsed_files = self._parse_raw_unified_diff(diff_resp.text)
                            if parsed_files:
                                files = parsed_files
                                await logger.ainfo(
                                    "github_large_commit_raw_diff_parsed",
                                    sha=sha,
                                    total_files=len(files),
                                )
                    except Exception as e:
                        await logger.awarning("github_large_commit_raw_diff_failed", error=str(e))

                # If steam.inf is still not in the list, or is present without inline patch,
                # fetch its raw content directly by commit SHA.
                has_steam_inf = any(f.get("filename", "").endswith("steam.inf") for f in files)
                if not has_steam_inf:
                    raw_url = f"https://raw.githubusercontent.com/SteamTracking/GameTracking-CS2/{sha}/game/csgo/steam.inf"
                    try:
                        raw_resp = await client.get(raw_url, headers=self._get_headers(), follow_redirects=True)
                        if raw_resp.status_code == 200:
                            files.append({
                                "filename": "game/csgo/steam.inf",
                                "patch": raw_resp.text,
                                "status": "modified",
                            })
                    except Exception as e:
                        await logger.awarning("steam_inf_direct_fetch_failed", error=str(e))
                else:
                    for f in files:
                        if f.get("filename", "").endswith("steam.inf") and not f.get("patch"):
                            raw_url = f.get("raw_url") or f"https://raw.githubusercontent.com/SteamTracking/GameTracking-CS2/{sha}/game/csgo/steam.inf"
                            try:
                                raw_resp = await client.get(raw_url, headers=self._get_headers(), follow_redirects=True)
                                if raw_resp.status_code == 200:
                                    f["patch"] = raw_resp.text
                            except Exception as e:
                                await logger.awarning("steam_inf_raw_fetch_failed", error=str(e))
                            break

                return self._parse_commit_data(sha, commit_html_url, commit_dt, files)

        except httpx.TimeoutException:
            await logger.awarning("github_datamine_timeout")
        except Exception as e:
            await logger.aerror("github_datamine_error", error=str(e), exc_info=True)

        return None

    @staticmethod
    def _parse_raw_unified_diff(diff_text: str) -> list[dict[str, Any]]:
        """Parse a raw unified git diff into file dicts handling spaces, renames, and deletions."""

        def _clean_path(raw: str, prefix: str) -> str:
            val = raw.rstrip("\t").strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            return val.removeprefix(prefix)

        parsed_files: list[dict[str, Any]] = []
        for chunk in re.split(r"(?m)^diff --git ", diff_text)[1:]:
            lines = chunk.splitlines()
            if not lines:
                continue

            header_line = lines[0]
            status = "modified"
            filename: str | None = None
            old_filename: str | None = None

            for line in lines[1:12]:
                if line.startswith("@@"):
                    break
                if line.startswith("new file mode "):
                    status = "added"
                elif line.startswith("deleted file mode "):
                    status = "removed"
                elif line.startswith("rename to "):
                    status = "renamed"
                    filename = _clean_path(line[len("rename to "):], "")
                elif line.startswith("rename from "):
                    old_filename = _clean_path(line[len("rename from "):], "")
                elif line.startswith("--- /dev/null"):
                    status = "added"
                elif line.startswith("--- "):
                    old_filename = _clean_path(line[len("--- "):], "a/")
                elif line.startswith("+++ /dev/null"):
                    status = "removed"
                elif line.startswith("+++ "):
                    filename = _clean_path(line[len("+++ "):], "b/")

            if status == "removed" and old_filename:
                filename = old_filename
            elif not filename:
                match = re.match(r'^"?a/(.+?)"?\s+"?b/(.+?)"?$', header_line.strip())
                if match:
                    filename = match.group(1) if status == "removed" else match.group(2)
                else:
                    filename = _clean_path(header_line.split()[0], "a/")

            parsed_files.append({
                "filename": filename,
                "patch": "\n".join(lines[1:]),
                "status": status,
            })

        return parsed_files

    @staticmethod
    def _summarize_pak01_patch(patch: str) -> str:
        """
        Produce a comprehensive, high-signal summary of asset changes in pak01_dir.vpk.
        Categorizes: animations, particles/effects, sounds/music, maps/collisions,
        models/textures, UI/Panorama images, scripts/configs, and lists exact notable asset paths.
        """
        from collections import Counter

        lines = patch.splitlines()
        added = [l[1:].strip() for l in lines if l.startswith("+") and not l.startswith("+++")]
        removed = [l[1:].strip() for l in lines if l.startswith("-") and not l.startswith("---")]

        if not added and not removed:
            return ""

        ext_counts: Counter[str] = Counter()
        anim_details: list[str] = []
        particle_details: list[str] = []
        sound_details: list[str] = []
        map_details: list[str] = []
        ui_details: list[str] = []
        loc_details: list[str] = []
        model_details: list[str] = []
        notable_assets_by_cat: dict[str, list[str]] = {
            "animations": [],
            "models": [],
            "particles": [],
            "sounds": [],
            "maps": [],
            "ui": [],
            "localization": [],
            "other": [],
        }

        for line in added:
            path = line.split()[0] if line else ""
            if not path:
                continue
            ext = path.split(".")[-1].lower() if "." in path else ""
            ext_counts[ext] += 1
            filename_only = path.split("/")[-1]

            # 1. Animations (with exact weapon & clip name)
            if ext in ("vnmclip_c", "vanim_c", "vnmgraph_c") or "animation" in path or "anims" in path:
                # e.g. animation/anims/viewmodel/rifle/rifle_awp/reload_silent_awp.vnmclip_c
                clip_clean = re.sub(r"\.(vnmclip_c|vanim_c|vnmgraph_c)$", "", filename_only)
                # Find weapon prefix if available
                parts = path.split("/")
                weapon_name = ""
                for p in parts:
                    if any(p.startswith(pr) for pr in ["pistol_", "weapon_", "rifle_", "smg_", "knife_"]):
                        weapon_name = re.sub(r"^(pistol_|weapon_|rifle_|smg_)", "", p)
                        break
                label = f"{weapon_name}: {clip_clean}" if weapon_name else clip_clean
                if label not in anim_details and len(anim_details) < 25:
                    anim_details.append(label)
                if path not in notable_assets_by_cat["animations"] and len(notable_assets_by_cat["animations"]) < 35:
                    notable_assets_by_cat["animations"].append(path)

            # 2. Particles & Visual Effects (molotov, smoke, snow, flame, etc.)
            elif ext in ("vpcf_c", "vpcf") or "particles" in path:
                part_name = re.sub(r"\.(vpcf_c|vpcf)$", "", filename_only)
                if part_name not in particle_details and len(particle_details) < 25:
                    particle_details.append(part_name)
                if path not in notable_assets_by_cat["particles"] and len(notable_assets_by_cat["particles"]) < 25:
                    notable_assets_by_cat["particles"].append(path)

            # 3. Sounds & Music (weapons, music kits, bomb, environment)
            elif ext in ("vsnd_c", "vsndevts_c", "vsndstck_c") or "soundevents" in path or "sound" in path:
                snd_name = re.sub(r"\.(vsnd_c|vsndevts_c|vsndstck_c)$", "", filename_only)
                if snd_name not in sound_details and len(sound_details) < 25:
                    sound_details.append(snd_name)
                if path not in notable_assets_by_cat["sounds"] and len(notable_assets_by_cat["sounds"]) < 35:
                    notable_assets_by_cat["sounds"].append(path)

            # 4. Maps & Physics/Collisions
            elif "maps/" in path or ext in ("vpk", "vphys_c"):
                parts = path.split("/")
                m_label = filename_only
                for p in parts:
                    if p.startswith("de_") or p.startswith("cs_") or p.startswith("ar_"):
                        m_label = p.split(".")[0]
                        break
                if ext == "vphys_c":
                    m_label += " (коллизии/физика)"
                if m_label not in map_details and len(map_details) < 25:
                    map_details.append(m_label)
                if path not in notable_assets_by_cat["maps"] and len(notable_assets_by_cat["maps"]) < 30:
                    notable_assets_by_cat["maps"].append(path)

            # 5. Panorama UI Images & Previews (map screenshots, store, icons, banners)
            elif "panorama" in path and ext in ("png", "svg", "jpg", "jpeg", "webp"):
                ui_clean = re.sub(r"\.(png|svg|jpg|jpeg|webp)$", "", filename_only)
                if ui_clean not in ui_details and len(ui_details) < 25:
                    ui_details.append(ui_clean)
                if path not in notable_assets_by_cat["ui"] and len(notable_assets_by_cat["ui"]) < 35:
                    notable_assets_by_cat["ui"].append(path)

            # 6. Localization files (resource/csgo_*.txt)
            elif "resource/csgo_" in path or ("resource/" in path and ext == "txt"):
                lang_match = re.search(r"csgo_([a-zA-Z0-9_]+)\.txt", filename_only)
                lang_name = lang_match.group(1) if lang_match else filename_only
                if lang_name not in loc_details and len(loc_details) < 35:
                    loc_details.append(lang_name)
                if path not in notable_assets_by_cat["localization"] and len(notable_assets_by_cat["localization"]) < 35:
                    notable_assets_by_cat["localization"].append(path)

            # 7. Models, Materials & Props (de_cbble doors, props, trims, weapons)
            elif ext in ("vmdl_c", "vmdl", "vmat_c", "vsmart_c", "vtex_c") or "models/" in path or "materials/" in path:
                clean_name = re.sub(r"\.(vmdl_c|vmdl|vmat_c|vsmart_c|vtex_c)$", "", filename_only)
                if any(kw in path.lower() for kw in ["cbble", "inferno", "nuke", "dust", "mirage", "anubis", "vertigo", "overpass", "door", "trim", "window", "pillar", "gate", "wall", "bomb", "c4", "weapon", "arms", "glove"]):
                    if clean_name not in model_details and len(model_details) < 40:
                        model_details.append(clean_name)
                    if path not in notable_assets_by_cat["models"] and len(notable_assets_by_cat["models"]) < 80:
                        notable_assets_by_cat["models"].append(path)

            # 8. Other notable items (c4, bomb, freeze, taser, chicken)
            elif any(kw in path.lower() for kw in ["c4", "bomb", "freeze", "chicken", "taser", "zeus", "retake", "defuse"]):
                if path not in notable_assets_by_cat["other"] and len(notable_assets_by_cat["other"]) < 25:
                    notable_assets_by_cat["other"].append(path)

        summary_lines = [
            "--- a/game/csgo/pak01_dir.txt (Сводка изменений в архиве игры pak01.vpk)",
            "+++ b/game/csgo/pak01_dir.txt",
            f"# Всего добавлено/обновлено файлов: {len(added)}, удалено/заменено: {len(removed)}",
        ]

        # Animations
        anim_count = ext_counts.get("vnmclip_c", 0) + ext_counts.get("vanim_c", 0)
        graph_count = ext_counts.get("vnmgraph_c", 0)
        if anim_count > 0 or graph_count > 0:
            anim_desc = f"# • Анимации: обновлено {anim_count} клипов анимаций"
            if graph_count > 0:
                anim_desc += f", {graph_count} граф анимаций"
            if anim_details:
                anim_desc += f" (действия: {', '.join(anim_details[:15])})"
            summary_lines.append(anim_desc)

        # Particles & Effects
        part_count = ext_counts.get("vpcf_c", 0) + ext_counts.get("vpcf", 0)
        if part_count > 0 or particle_details:
            part_desc = f"# • Частицы и визуальные эффекты: {part_count} файлов"
            if particle_details:
                part_desc += f" (эффекты: {', '.join(particle_details[:15])})"
            summary_lines.append(part_desc)

        # Sounds & Music
        sound_count = ext_counts.get("vsnd_c", 0) + ext_counts.get("vsndevts_c", 0) + ext_counts.get("vsndstck_c", 0)
        if sound_count > 0 or sound_details:
            snd_desc = f"# • Звуки и аудио: {sound_count} звуковых файлов"
            if sound_details:
                snd_desc += f" (названия: {', '.join(sound_details[:15])})"
            summary_lines.append(snd_desc)

        # Maps & Collisions
        map_count = ext_counts.get("vpk", 0) + ext_counts.get("vphys_c", 0)
        if map_details or map_count > 0:
            summary_lines.append(f"# • Карты и коллизии ({map_count} файлов): {', '.join(map_details[:15])}")

        # Panorama UI Images & Previews
        img_count = sum(ext_counts.get(e, 0) for e in ("png", "svg", "jpg", "jpeg", "webp"))
        if img_count > 0 or ui_details:
            summary_lines.append(f"# • Изображения интерфейса и превью карт ({img_count} файлов): {', '.join(ui_details[:15])}")

        # Models & Textures
        model_count = ext_counts.get("vmdl_c", 0) + ext_counts.get("vmdl", 0)
        tex_count = ext_counts.get("vtex_c", 0) + ext_counts.get("vmat_c", 0) + ext_counts.get("vcompmat_c", 0)
        if model_count > 0 or tex_count > 0:
            m_desc = f"# • Модели и текстуры: {model_count} моделей, {tex_count} текстур/материалов"
            if model_details:
                m_desc += f" (ключевые объекты: {', '.join(model_details[:20])})"
            summary_lines.append(m_desc)

        # Localization & Language Strings
        if loc_details:
            summary_lines.append(
                f"# • Локализация и языковые файлы ({len(loc_details)} языков): обновлены строки для {', '.join(loc_details[:25])}"
            )

        # Scripts / Logic
        script_count = ext_counts.get("kv3", 0) + ext_counts.get("txt", 0) + ext_counts.get("vdata", 0)
        if script_count > 0:
            summary_lines.append(f"# • Игровые скрипты и конфиги: {script_count} файлов в архиве")

        # Explicit list of notable asset filepaths (balanced across all categories)
        notable_assets: list[str] = []
        for cat in ("animations", "models", "maps", "localization", "ui", "particles", "sounds", "other"):
            notable_assets.extend(notable_assets_by_cat[cat])

        if notable_assets:
            summary_lines.append(f"# • Ключевые изменённые ассеты (первые {min(len(notable_assets), 350)} файлов):")
            for asset in notable_assets[:350]:
                summary_lines.append(f"#   - {asset}")

        return "\n".join(summary_lines) + "\n"

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
                patch_content = f.get("patch") or ""
                patch_ver_match = re.search(r"^\+?PatchVersion=([0-9.]+)", patch_content, re.MULTILINE)
                if patch_ver_match:
                    patch_version = patch_ver_match.group(1).strip()

                client_ver_match = re.search(r"^\+?ClientVersion=([0-9.]+)", patch_content, re.MULTILINE)
                if client_ver_match:
                    client_version = client_ver_match.group(1).strip()

                server_ver_match = re.search(r"^\+?ServerVersion=([0-9.]+)", patch_content, re.MULTILINE)
                if server_ver_match:
                    server_version = server_ver_match.group(1).strip()
                break

        # 2. Group files by priority
        prioritized_files: list[list[tuple[str, str]]] = [[] for _ in PRIORITY_PATTERNS]
        matched_filenames: list[str] = []

        # Summarize pak01_dir.txt if present
        pak01_summary = ""
        for f in files:
            if f.get("filename", "").endswith("pak01_dir.txt"):
                patch = f.get("patch") or ""
                if patch:
                    pak01_summary = self._summarize_pak01_patch(patch)
                    matched_filenames.append("game/csgo/pak01_dir.txt (summary)")
                break

        for f in files:
            filename = f.get("filename", "")
            patch = f.get("patch", "")
            if not patch or filename.endswith("pak01_dir.txt"):
                continue

            for idx, (_, pattern) in enumerate(PRIORITY_PATTERNS):
                if pattern.match(filename):
                    prioritized_files[idx].append((filename, patch))
                    matched_filenames.append(filename)
                    break

        # 3. Assemble filtered diff up to self.max_diff_chars (250k tokens budget)
        diff_chunks: list[str] = []
        current_len = 0
        has_relevant = False

        if pak01_summary:
            diff_chunks.append(pak01_summary)
            current_len += len(pak01_summary)
            has_relevant = True

        # Cap single files to 160,000 chars so one runaway dump doesn't monopolize the 850k budget
        single_file_max_chars = 160000

        for idx, group in enumerate(prioritized_files):
            group_name = PRIORITY_PATTERNS[idx][0]

            for filename, patch in group:
                has_relevant = True
                chunk_header = f"--- a/{filename}\n+++ b/{filename}\n"
                chunk_budget = self.max_diff_chars - current_len - len(chunk_header)

                if chunk_budget <= 200:
                    break

                # For localization files, highlight newly added strings (music kits, items, tournament labels)
                loc_added_summary = ""
                if "csgo_russian.txt" in filename or "csgo_english.txt" in filename:
                    added_lines = [
                        l[1:].strip()
                        for l in patch.splitlines()
                        if l.startswith("+") and not l.startswith("+++") and '"' in l
                    ]
                    if added_lines:
                        loc_added_summary = (
                            f"# [Выделенные новые строки локализации ({filename.split('/')[-1]})]:\n"
                            + "\n".join(f"#  + {line}" for line in added_lines[:100])
                            + "\n\n"
                        )

                patch_to_add = patch
                if len(patch_to_add) > single_file_max_chars:
                    patch_to_add = patch_to_add[:single_file_max_chars] + "\n... [diff truncated to 160k chars]"

                if len(patch_to_add) > chunk_budget:
                    patch_to_add = patch_to_add[:chunk_budget] + "\n... [diff truncated due to overall budget]"

                full_chunk = chunk_header + loc_added_summary + patch_to_add
                diff_chunks.append(full_chunk)
                current_len += len(full_chunk)

                if current_len >= self.max_diff_chars:
                    break

            if current_len >= self.max_diff_chars:
                break

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
