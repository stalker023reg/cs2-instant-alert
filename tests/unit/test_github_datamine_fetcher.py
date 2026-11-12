"""Tests for GitHubDatamineFetcher blind spot fixes."""

from datetime import datetime, UTC
import pytest
from app.services.github_datamine_fetcher import GitHubDatamineFetcher, PRIORITY_PATTERNS


class TestGitHubDatamineFetcherBlindSpots:
    def test_priority_patterns_match_blind_spot_files(self):
        """Ensure gameinfo.gi, .kv3, video_defaults, and fgd/schemas match priority patterns."""
        files_to_test = [
            ("game/csgo/gameinfo.gi", "configs"),
            ("game/csgo/pak01_dir/cfg/video_defaults_0.txt", "configs"),
            ("game/csgo/cfg/gamemode_retakecasual.cfg", "configs"),
            ("game/csgo/pak01_dir/scripts/ai/retakes/bt_config.kv3", "scripts"),
            ("scripts/weapons/weapon_ak47.txt", "scripts"),
            ("game/csgo/csgo.fgd", "fgd"),
            ("DumpSource2/entities/server.fgd", "fgd"),
            ("DumpSource2/schemas/server/CCSPlayerPawn.h", "schemas"),
        ]

        for filename, expected_group in files_to_test:
            matched_group = None
            for group, pat in PRIORITY_PATTERNS:
                if pat.match(filename):
                    matched_group = group
                    break
            assert matched_group == expected_group, f"{filename} should match {expected_group}, got {matched_group}"

    def test_parse_commit_data_extracts_version_with_and_without_plus(self):
        """steam.inf should parse whether prefixed with + (diff) or bare (raw file)."""
        fetcher = GitHubDatamineFetcher()

        # Case 1: Git diff format (+PatchVersion)
        files_diff = [
            {
                "filename": "game/csgo/steam.inf",
                "patch": "--- a/game/csgo/steam.inf\n+++ b/game/csgo/steam.inf\n+PatchVersion=1.41.9.7\n+ClientVersion=2000943\n+ServerVersion=2000943\n",
            }
        ]
        res1 = fetcher._parse_commit_data("sha1", "url", datetime.now(UTC), files_diff)
        assert res1.patch_version == "1.41.9.7"
        assert res1.client_version == "2000943"
        assert res1.server_version == "2000943"

        # Case 2: Raw file format (PatchVersion without +)
        files_raw = [
            {
                "filename": "game/csgo/steam.inf",
                "patch": "ClientVersion=2000943\nServerVersion=2000943\nPatchVersion=1.41.9.7\nProductName=cs2\n",
            }
        ]
        res2 = fetcher._parse_commit_data("sha2", "url", datetime.now(UTC), files_raw)
        assert res2.patch_version == "1.41.9.7"
        assert res2.client_version == "2000943"
        assert res2.server_version == "2000943"

    def test_summarize_pak01_patch(self):
        """pak01_dir.txt patch should be summarized into a high-level concise breakdown."""
        fetcher = GitHubDatamineFetcher()
        mock_pak_patch = """
@@ -10,6 +10,10 @@
+animation/anims/world/pistol/pistol_cz75a/draw_cz75a.vnmclip_c CRC:123 size:1000
+animation/anims/world/pistol/pistol_cz75a/reload_cz75a.vnmclip_c CRC:124 size:2000
+animation/graphs/worldmodel/worldmodel.vnmgraph_c CRC:125 size:50000
+models/weapons/v_models/arms/glove_handwrap_leathery/glove_handwrap_leathery.vmdl_c CRC:126 size:3000
+materials/models/weapons/customization/c4_timer/c4_timer.vtex_c CRC:127 size:4000
+scripts/ai/retakes/bt_config.kv3 CRC:128 size:500
-animation/anims/world/pistol/pistol_cz75a/draw_cz75a.vnmclip_c CRC:000 size:900
"""
        summary = fetcher._summarize_pak01_patch(mock_pak_patch)
        assert "pak01_dir.txt" in summary
        assert "2 клипов анимаций" in summary
        assert "1 граф анимаций" in summary
        assert "cz75a" in summary
        assert "Модели и текстуры: 1 моделей, 1 текстур/материалов" in summary
        assert "Игровые скрипты и конфиги: 1 файлов в архиве" in summary
        assert "c4_timer.vtex_c" in summary

    def test_pak01_summary_is_included_in_parsed_diff(self):
        """pak01_dir.txt summary should be injected into assembled filtered diff."""
        fetcher = GitHubDatamineFetcher()
        files = [
            {
                "filename": "game/csgo/pak01_dir.txt",
                "patch": "+animation/anims/world/pistol/pistol_cz75a/draw_cz75a.vnmclip_c CRC:123 size:1000\n",
            },
            {
                "filename": "DumpSource2/convars.txt",
                "patch": "+r_csgo_parallax 1\n",
            },
        ]
        res = fetcher._parse_commit_data("sha3", "url", datetime.now(UTC), files)
        assert "game/csgo/pak01_dir.txt (summary)" in res.matched_files
        assert "DumpSource2/convars.txt" in res.matched_files
        assert "Сводка изменений в архиве игры pak01.vpk" in res.filtered_diff
        assert "r_csgo_parallax 1" in res.filtered_diff
        assert res.has_relevant_changes is True

