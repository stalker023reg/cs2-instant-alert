"""
Unit tests for Gemini AI Analysis Service, depot diff helpers, and notification formatting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from pydantic import SecretStr

from app.events.types import UpdateDetectedEvent
from app.notifications.formatter import TelegramFormatter
from app.services.gemini_analysis_service import (
    CS2_DEPOT_NAMES,
    GeminiAnalysisService,
    UpdateAnalysis,
)
from app.steam.types import AppUpdateData, BranchInfo, DepotInfo, SteamSource


# ─── GeminiAnalysisService Tests ───


class TestGeminiAnalysisService:
    def test_init_without_key(self) -> None:
        service = GeminiAnalysisService(api_key=None)
        assert service.is_available is False

    def test_init_with_secret_str(self) -> None:
        with patch("google.genai.Client") as mock_client_cls:
            service = GeminiAnalysisService(api_key=SecretStr("fake-secret-key"))
            assert service.is_available is True
            mock_client_cls.assert_called_once_with(api_key="fake-secret-key")

    def test_init_with_plain_string(self) -> None:
        with patch("google.genai.Client") as mock_client_cls:
            service = GeminiAnalysisService(api_key="my-api-key")
            assert service.is_available is True
            mock_client_cls.assert_called_once_with(api_key="my-api-key")

    def test_sanitize_telegram_html(self) -> None:
        service = GeminiAnalysisService(api_key=None)
        raw_text = (
            "### Header 3\n"
            "**Bold Markdown** and <b>HTML Bold</b>\n"
            "<script>alert('bad')</script>\n"
            "```python\nprint(1)\n```\n"
            "<i>Italic</i> and <code>code</code>\n"
            "<div>bad div</div>"
        )
        cleaned = service._sanitize_telegram_html(raw_text)

        assert "###" not in cleaned
        assert "**" not in cleaned
        assert "<b>HTML Bold</b>" in cleaned
        assert "<script>" not in cleaned
        assert "<div>" not in cleaned
        assert "<i>Italic</i>" in cleaned
        assert "<code>code</code>" in cleaned

    def test_sanitize_telegram_html_truncates_long_text(self) -> None:
        service = GeminiAnalysisService(api_key=None)
        long_text = "A" * 3000
        cleaned = service._sanitize_telegram_html(long_text)
        assert len(cleaned) < 2600
        assert "<i>…продолжение по ссылке</i>" in cleaned

    def test_build_depot_context_empty(self) -> None:
        service = GeminiAnalysisService(api_key=None)
        assert service._build_depot_context(None) == ""
        assert service._build_depot_context({}) == ""

    def test_build_depot_context_with_diff_dict(self) -> None:
        service = GeminiAnalysisService(api_key=None)
        manifest_changes = {
            "733": {
                "name": "CS2 Binaries (Win64)",
                "old_manifest": "11111",
                "new_manifest": "22222",
                "size_bytes": 5000000,
            },
            "731": "33333",
        }
        context = service._build_depot_context(manifest_changes)
        assert "CS2 Binaries (Win64)" in context
        assert "11111" in context
        assert "22222" in context
        assert "CS2 Client Content" in context
        assert "33333" in context

    def test_format_depot_diff_html(self) -> None:
        service = GeminiAnalysisService(api_key=None)
        manifest_changes = {
            "730": "123",
            "733": "456",
        }
        html = service._format_depot_diff_html(manifest_changes)
        assert "CS2 Shared Content" in html
        assert "CS2 Binaries (Win64)" in html
        assert "<b>" in html

    def test_fallback_analysis_formats_bbcode(self) -> None:
        service = GeminiAnalysisService(api_key=None)
        bbcode = "[p]\\[ GAMEPLAY ][/p]\n[list]\n[*][p]Fixed bug with smoke[/p][/*]\n[/list]"
        res = service._fallback_analysis(bbcode)
        assert isinstance(res, UpdateAnalysis)
        assert "🎮 <b>GAMEPLAY</b>" in res.summary_html
        assert "🛠 Fixed bug with smoke" in res.summary_html

    @pytest.mark.asyncio
    async def test_analyze_update_fallback_when_not_available(self) -> None:
        service = GeminiAnalysisService(api_key=None)
        bbcode = "[p]\\[ GAMEPLAY ][/p]\n[list]\n[*][p]Fixed bug[/p][/*]\n[/list]"
        analysis = await service.analyze_update(bbcode)
        assert "🎮 <b>GAMEPLAY</b>" in analysis.summary_html
        assert analysis.depot_diff_html is None
        assert analysis.error is None

    @pytest.mark.asyncio
    async def test_analyze_update_calls_gemini_api(self) -> None:
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            # Setup mock aio response
            mock_response = MagicMock()
            mock_response.text = "<b>TL;DR:</b> Обновление физики гранат.\n🎮 <b>Геймплей</b>\n▸ Улучшена физика"
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

            service = GeminiAnalysisService(api_key="valid-key")
            manifest_changes = {"733": "99999"}

            analysis = await service.analyze_update(
                raw_patch_notes="[b]Patch Notes[/b]",
                manifest_changes=manifest_changes,
            )

            assert "<b>TL;DR:</b>" in analysis.summary_html
            assert analysis.depot_diff_html is not None
            assert "CS2 Binaries (Win64)" in analysis.depot_diff_html
            assert analysis.error is None
            mock_client.aio.models.generate_content.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_analyze_update_silent_update(self) -> None:
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            mock_response = MagicMock()
            mock_response.text = "<b>TL;DR:</b> Бесшумный патч для серверов.\n⚙️ <b>Прочее</b>\n• Обновлены бинарники"
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

            service = GeminiAnalysisService(api_key="valid-key")
            manifest_changes = {"731": "111", "733": "222"}

            analysis = await service.analyze_update(
                raw_patch_notes=None,
                manifest_changes=manifest_changes,
            )

            assert "Бесшумный патч" in analysis.summary_html
            assert "CS2 Client Content" in analysis.depot_diff_html
            assert "CS2 Binaries (Win64)" in analysis.depot_diff_html
            assert analysis.error is None

            # Verify prompt instructed silent update
            call_kwargs = mock_client.aio.models.generate_content.await_args.kwargs
            prompt = call_kwargs["contents"]
            assert "бесшумный патч" in prompt.lower()

    def test_build_prompt_undocumented_changes_instruction(self) -> None:
        service = GeminiAnalysisService(api_key=None)
        prompt = service._build_prompt(
            raw_patch_notes="Fixed mirage gap",
            depot_context="- CS2 Binaries (Win64): new manifest",
        )
        assert "Недокументированные изменения" in prompt
        assert "Depot Changes" in prompt


# ─── Depot Diff Helper Tests ───


class TestDepotDiffHelpers:
    def test_get_manifest_dict(self) -> None:
        data = AppUpdateData(
            app_id=730,
            source=SteamSource.PICS,
            checked_at=datetime.now(UTC),
            depots={
                730: DepotInfo(depot_id=730, manifest_id="111"),
                731: DepotInfo(depot_id=731, manifest_id=None),
                733: DepotInfo(depot_id=733, manifest_id="222"),
            },
        )
        assert data.get_manifest_dict() == {"730": "111", "733": "222"}

    def test_compute_depot_diff_without_previous(self) -> None:
        data = AppUpdateData(
            app_id=730,
            source=SteamSource.PICS,
            checked_at=datetime.now(UTC),
            depots={
                733: DepotInfo(depot_id=733, name="Binaries", manifest_id="222", size_bytes=1000),
            },
        )
        diff = data.compute_depot_diff(previous_manifests=None)
        assert "733" in diff
        assert diff["733"]["old_manifest"] is None
        assert diff["733"]["new_manifest"] == "222"
        assert diff["733"]["size_bytes"] == 1000

    def test_compute_depot_diff_with_previous(self) -> None:
        previous = {"730": "111", "733": "222"}
        data = AppUpdateData(
            app_id=730,
            source=SteamSource.PICS,
            checked_at=datetime.now(UTC),
            depots={
                730: DepotInfo(depot_id=730, manifest_id="111"),  # Unchanged
                733: DepotInfo(depot_id=733, manifest_id="333"),  # Changed!
                731: DepotInfo(depot_id=731, manifest_id="444"),  # Added!
            },
        )
        diff = data.compute_depot_diff(previous_manifests=previous)
        assert "730" not in diff  # Unchanged depot omitted
        assert "733" in diff
        assert diff["733"]["old_manifest"] == "222"
        assert diff["733"]["new_manifest"] == "333"
        assert "731" in diff
        assert diff["731"]["old_manifest"] is None
        assert diff["731"]["new_manifest"] == "444"


# ─── Formatter AI Tests ───


class TestFormatterAIAlert:
    def test_formatter_with_ai_analysis_header(self) -> None:
        raw_data = AppUpdateData(
            app_id=730,
            source=SteamSource.PICS,
            checked_at=datetime.now(UTC),
        )
        event = UpdateDetectedEvent(
            update_id=uuid.uuid4(),
            game_id=uuid.uuid4(),
            build_id="12345",
            previous_build_id="12344",
            detected_at=datetime.now(UTC),
            is_critical=True,
            raw_data=raw_data,
        )

        message = TelegramFormatter.format_update_alert(
            event=event,
            timezone="UTC",
            patch_notes_html="<b>TL;DR:</b> Важный патч",
            patch_url="https://store.steampowered.com/news/123",
            ai_analyzed=True,
            depot_diff_html="  📦 <b>CS2 Binaries (Win64)</b>",
        )

        assert "🤖 <b>Разбор обновления (AI + Датамайнинг)</b>" in message
        assert "📋 <b>Patch Notes</b>" not in message
        assert "📦 <b>Изменённые компоненты</b>" in message
        assert "CS2 Binaries (Win64)" in message
        assert "https://store.steampowered.com/news/123" in message

    def test_formatter_without_ai_analysis_fallback(self) -> None:
        raw_data = AppUpdateData(
            app_id=730,
            source=SteamSource.PICS,
            checked_at=datetime.now(UTC),
        )
        event = UpdateDetectedEvent(
            update_id=uuid.uuid4(),
            game_id=uuid.uuid4(),
            build_id="12345",
            previous_build_id=None,
            detected_at=datetime.now(UTC),
            is_critical=False,
            raw_data=raw_data,
        )

        message = TelegramFormatter.format_update_alert(
            event=event,
            timezone="UTC",
            patch_notes_html="Some raw patch notes",
            ai_analyzed=False,
            depot_diff_html=None,
        )

        assert "📋 <b>Patch Notes</b>" in message
        assert "🤖 <b>Разбор обновления" not in message
        assert "📦 <b>Изменённые компоненты</b>" not in message

    def test_formatter_silent_update_ai_header(self) -> None:
        raw_data = AppUpdateData(
            app_id=730,
            source=SteamSource.PICS,
            checked_at=datetime.now(UTC),
        )
        event = UpdateDetectedEvent(
            update_id=uuid.uuid4(),
            game_id=uuid.uuid4(),
            build_id="12345",
            previous_build_id="12344",
            detected_at=datetime.now(UTC),
            is_critical=True,
            raw_data=raw_data,
        )

        message = TelegramFormatter.format_update_alert(
            event=event,
            timezone="UTC",
            patch_notes_html="<b>TL;DR:</b> Бесшумный хотфикс",
            patch_url=None,  # No steam community URL -> Silent update!
            ai_analyzed=True,
            depot_diff_html="  📦 <b>CS2 Binaries (Win64)</b>",
        )

        assert "🤖 <b>Разбор обновления (AI + Датамайнинг)</b>" in message
        assert "📦 <b>Изменённые компоненты</b>" in message
        assert "CS2 Binaries (Win64)" in message

    def test_formatter_initial_alert_with_depot_diff(self) -> None:
        raw_data = AppUpdateData(
            app_id=730,
            source=SteamSource.PICS,
            checked_at=datetime.now(UTC),
        )
        event = UpdateDetectedEvent(
            update_id=uuid.uuid4(),
            game_id=uuid.uuid4(),
            build_id="12345",
            previous_build_id="12344",
            detected_at=datetime.now(UTC),
            is_critical=True,
            raw_data=raw_data,
        )

        # In initial alert, patch_notes_html is None, but depot_diff_html is known
        message = TelegramFormatter.format_update_alert(
            event=event,
            timezone="UTC",
            patch_notes_html=None,
            depot_diff_html="  📦 <b>CS2 Dedicated Server</b>",
        )

        assert "📦 <b>Изменённые компоненты</b>" in message
        assert "CS2 Dedicated Server" in message
        assert "Анализируем файлы обновления и ждем распаковку дампа" in message
