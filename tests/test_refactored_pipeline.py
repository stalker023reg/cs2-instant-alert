"""
Unit tests for the refactored two-stage datamining pipeline:
- Depot filtering (client-only)
- TelegramFormatter Stage 1 & Stage 2
- GitHubDatamineFetcher parsing and prioritization
- SteamNewsFetcher
- Gemini prompt generation and sanitization
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
import uuid

from app.utils.depot_filter import (
    CS2_DEPOT_NAMES,
    determine_criticality,
    filter_depots,
    format_depots_html,
)
from app.notifications.formatter import TelegramFormatter
from app.events.types import UpdateDetectedEvent
from app.steam.types import AppUpdateData, SteamSource
from app.services.github_datamine_fetcher import GitHubDatamineFetcher
from app.services.gemini_analysis_service import GeminiAnalysisService


class TestDepotFilter(unittest.TestCase):
    def test_filter_macos_and_server_and_technical_depots(self):
        # 731: client content (keep)
        # 733: client binaries (keep)
        # 732: dedicated server (discard)
        # 735: macOS binary (discard)
        # 2347779: macOS content (discard)
        # 736: technical depot (collapse)
        # 737: technical depot (collapse)
        raw_depots = {
            "731": {"name": "CS2 Client Content"},
            "733": {"name": "CS2 Binaries (Win64)"},
            "732": {"name": "CS2 Dedicated Server"},
            "735": {"name": "CS2 Binaries (macOS)"},
            "2347779": {"name": "CS2 Content (macOS)"},
            "736": {"name": ""},
            "737": {"name": ""},
        }

        filtered, tech_count = filter_depots(raw_depots)
        filtered_ids = [d["depot_id"] for d in filtered]

        self.assertIn(731, filtered_ids)
        self.assertIn(733, filtered_ids)
        self.assertNotIn(732, filtered_ids)
        self.assertNotIn(735, filtered_ids)
        self.assertNotIn(2347779, filtered_ids)
        self.assertNotIn(736, filtered_ids)
        self.assertNotIn(737, filtered_ids)
        self.assertEqual(tech_count, 2)


class TestTelegramFormatter(unittest.TestCase):
    def setUp(self):
        self.event = UpdateDetectedEvent(
            update_id=uuid.uuid4(),
            game_id=uuid.uuid4(),
            build_id="26087496",
            previous_build_id="26087111",
            is_critical=False,
            detected_at=datetime(2026, 10, 23, 11, 0, 0, tzinfo=UTC),
            raw_data=AppUpdateData(
                app_id=730,
                source=SteamSource.PICS,
                checked_at=datetime(2026, 10, 23, 11, 0, 0, tzinfo=UTC),
            ),
            depot_changes={"731": {"name": "CS2 Client Content"}},
        )

    def test_stage_1_instant_alert(self):
        filtered, tech_count = filter_depots(self.event.depot_changes)
        depot_html = format_depots_html(filtered, tech_count)

        msg = TelegramFormatter.format_update_alert(
            event=self.event,
            timezone="UTC",
            depot_diff_html=depot_html,
        )

        self.assertIn("Обновление CS2", msg)
        self.assertIn("26087496", msg)
        self.assertIn("26087111", msg)
        self.assertIn("CS2 Client Content", msg)
        self.assertIn("Анализируем файлы обновления и ждем распаковку дампа", msg)

    def test_stage_2_edited_alert(self):
        analysis_html = (
            "🧰 <b>Основной патчноут</b>\n• Исправлены ошибки на картах\n\n"
            "🕵️ <b>Не вошло в патчноут (Датамайнинг)</b>\n• <code>sv_cheats</code> обновлен"
        )
        msg = TelegramFormatter.format_update_alert(
            event=self.event,
            timezone="UTC",
            patch_notes_html=analysis_html,
            patch_version="1.41.9.2",
            patch_url="https://steamcommunity.com/announcements/detail/123",
            ai_analyzed=True,
        )

        self.assertIn("1.41.9.2", msg)
        self.assertIn("Разбор обновления (AI + Датамайнинг)", msg)
        self.assertIn("sv_cheats", msg)
        self.assertIn("https://steamcommunity.com/announcements/detail/123", msg)
        self.assertNotIn("Анализируем файлы обновления", msg)

    def test_stage_2_timeout_alert(self):
        msg = TelegramFormatter.format_update_alert(
            event=self.event,
            timezone="UTC",
            is_timeout=True,
        )
        self.assertIn("Техническое обновление без публичного списка изменений", msg)
        self.assertNotIn("Анализируем файлы обновления", msg)


class TestGitHubDatamineParsing(unittest.TestCase):
    def test_parse_commit_data(self):
        fetcher = GitHubDatamineFetcher()

        sample_files = [
            {
                "filename": "game/csgo/steam.inf",
                "patch": "@@ -1,9 +1,9 @@\n-ClientVersion=2000934\n+ClientVersion=2000935\n-ServerVersion=2000934\n+ServerVersion=2000935\n-PatchVersion=1.41.9.1\n+PatchVersion=1.41.9.2\n",
            },
            {
                "filename": "DumpSource2/convars.txt",
                "patch": "@@ -10,3 +10,4 @@\n+convar_test 1\n",
            },
            {
                "filename": "content/csgo_addons/cs_script_demo/maps/scripts/point_script.d.ts",
                "patch": "@@ -50,2 +50,4 @@\n+export interface TestScriptAPI {}\n",
            },
            {
                "filename": "game/csgo/pak01_dir/panorama/styles/hud/hud.css",
                "patch": "@@ -1,2 +1,3 @@\n+.hud_box { color: red; }\n",
            },
            {
                "filename": "ignored_folder/random.cpp",
                "patch": "+huge c++ dump that should be ignored",
            },
        ]

        result = fetcher._parse_commit_data(
            sha="abcdef123456",
            commit_url="https://github.com/test",
            commit_dt=datetime(2026, 10, 23, 11, 0, 0, tzinfo=UTC),
            files=sample_files,
        )

        self.assertEqual(result.patch_version, "1.41.9.2")
        self.assertEqual(result.client_version, "2000935")
        self.assertEqual(result.server_version, "2000935")
        self.assertTrue(result.has_relevant_changes)

        # Relevant files included
        self.assertIn("DumpSource2/convars.txt", result.matched_files)
        self.assertIn("content/csgo_addons/cs_script_demo/maps/scripts/point_script.d.ts", result.matched_files)
        self.assertIn("game/csgo/pak01_dir/panorama/styles/hud/hud.css", result.matched_files)
        # Irrelevant files excluded from matched_files
        self.assertNotIn("ignored_folder/random.cpp", result.matched_files)

        # Check diff content
        self.assertIn("convar_test 1", result.filtered_diff)
        self.assertIn("TestScriptAPI", result.filtered_diff)
        self.assertNotIn("huge c++ dump", result.filtered_diff)


class TestGeminiPromptAndSanitization(unittest.TestCase):
    def test_prompt_contains_anti_hallucination_rules(self):
        service = GeminiAnalysisService()
        prompt = service._build_prompt(
            raw_patch_notes="Fixed bomb sound bug.",
            git_diff="--- a/DumpSource2/convars.txt\n+++ b/DumpSource2/convars.txt\n+snd_bomb_fix 1",
            patch_version="1.41.9.2",
        )

        self.assertIn("ЗАПРЕТ НА ГАЛЛЮЦИНАЦИИ", prompt)
        self.assertIn("КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО выдумывать изменения", prompt)
        self.assertIn("1.41.9.2", prompt)
        self.assertIn("Fixed bomb sound bug.", prompt)
        self.assertIn("snd_bomb_fix 1", prompt)

    def test_sanitization(self):
        service = GeminiAnalysisService()
        raw = "## Header\n**Bold text** with `code` and <script>alert(1)</script> <div class='test'>content</div>"
        cleaned = service._sanitize_telegram_html(raw)
        self.assertNotIn("##", cleaned)
        self.assertNotIn("<script>", cleaned)
        self.assertNotIn("<div", cleaned)
        self.assertIn("<b>Bold text</b>", cleaned)
        self.assertIn("<code>code</code>", cleaned)
        self.assertIn("content", cleaned)


if __name__ == "__main__":
    unittest.main()
