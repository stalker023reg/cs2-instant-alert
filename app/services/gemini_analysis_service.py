"""
CS2 Instant Alert — Gemini AI Analysis Service.

Analyzes patch notes and depot changes using Google Gemini 2.5 Flash
to generate intelligent, structured summaries in Russian.

Replaces the DeepL translation step with a smarter AI-powered analysis
that categorizes changes, rates importance, and provides context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.logging import get_logger

logger = get_logger("system")

# ─── Known CS2 Depot IDs → Human-readable names ───
# Source: SteamDB — https://steamdb.info/app/730/depots/
CS2_DEPOT_NAMES: dict[int, str] = {
    730: "CS2 Shared Content",
    731: "CS2 Client Content",
    732: "CS2 Dedicated Server",
    733: "CS2 Binaries (Win64)",
    734: "CS2 Binaries (Linux64)",
    735: "CS2 Binaries (macOS)",
    2347770: "CS2 Content (Win64)",
    2347771: "CS2 Content (Linux64)",
    2347779: "CS2 Content (macOS)",
}


@dataclass
class UpdateAnalysis:
    """Result of AI analysis of a game update."""

    summary_html: str
    depot_diff_html: str | None = None
    importance: str = "medium"  # "critical", "medium", "minor"
    raw_response: str | None = None
    error: str | None = None


class GeminiAnalysisService:
    """
    Analyzes CS2 updates using Google Gemini 2.5 Flash.

    Free tier: 15 RPM / 1M tokens per minute — more than enough
    for 1-2 game updates per day.
    """

    MODEL = "gemini-3.8-flash"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-3.8-flash",
    ) -> None:
        self._client = None
        self.model = model

        # Handle Pydantic SecretStr objects from DI container
        actual_key = api_key
        if actual_key is not None and hasattr(actual_key, "get_secret_value"):
            actual_key = actual_key.get_secret_value()

        if actual_key:
            try:
                from google import genai

                self._client = genai.Client(api_key=actual_key)
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(f"Gemini init failed: {e}")

    @property
    def is_available(self) -> bool:
        """Check if the Gemini API client is properly initialized."""
        return self._client is not None

    # ─── Public API ───

    async def analyze_update(
        self,
        raw_patch_notes: str | None = None,
        manifest_changes: dict[str, Any] | None = None,
    ) -> UpdateAnalysis:
        """
        Analyze patch notes and depot changes, returning a structured AI summary.

        Supports both:
          1. Official patch notes analysis with detection of hidden/undocumented depot changes.
          2. Silent updates (no patch notes published) analyzed purely from depot diff.

        Falls back to basic BB-code formatting or status text if AI is unavailable or fails.

        Args:
            raw_patch_notes: Raw Steam BB-code patch notes text (or None if silent update).
            manifest_changes: Dict of depot_id -> manifest or change info.

        Returns:
            UpdateAnalysis with summary_html and optional depot_diff_html.
        """
        if not self._client:
            return self._fallback_analysis(raw_patch_notes)

        try:
            # Build depot context for the prompt
            depot_context = self._build_depot_context(manifest_changes)

            # Build the full prompt (adapts to whether patch notes are available)
            prompt = self._build_prompt(raw_patch_notes, depot_context)

            # Call Gemini Flash with automatic fallback across models if high demand
            models_to_try = [self.model]
            for fallback_name in ("gemini-flash-latest", "gemini-2.5-flash-lite"):
                if fallback_name not in models_to_try:
                    models_to_try.append(fallback_name)

            response = None
            used_model = self.model
            last_err = None

            for model_name in models_to_try:
                try:
                    response = await self._client.aio.models.generate_content(
                        model=model_name,
                        contents=prompt,
                    )
                    if response and response.text:
                        used_model = model_name
                        break
                except Exception as model_err:
                    last_err = model_err
                    await logger.awarning(
                        "gemini_model_attempt_failed",
                        model=model_name,
                        error=str(model_err),
                    )

            if not response or not response.text:
                if last_err:
                    raise last_err
                await logger.awarning("gemini_empty_response")
                return self._fallback_analysis(raw_patch_notes)

            ai_text = response.text.strip()

            # Post-process: ensure valid Telegram HTML
            summary_html = self._sanitize_telegram_html(ai_text)

            # Build depot diff HTML separately
            depot_diff_html = (
                self._format_depot_diff_html(manifest_changes)
                if manifest_changes
                else None
            )

            await logger.ainfo(
                "gemini_analysis_complete",
                input_len=len(raw_patch_notes) if raw_patch_notes else 0,
                output_len=len(summary_html),
                model=used_model,
                silent_update=not bool(raw_patch_notes),
            )

            return UpdateAnalysis(
                summary_html=summary_html,
                depot_diff_html=depot_diff_html,
                raw_response=ai_text,
            )

        except Exception as e:
            await logger.aerror("gemini_analysis_failed", error=str(e), exc_info=True)
            result = self._fallback_analysis(raw_patch_notes)
            result.error = str(e)
            return result

    # ─── Prompt Engineering ───

    def _build_prompt(self, raw_patch_notes: str | None, depot_context: str) -> str:
        """Build the analysis prompt for Gemini."""
        if not raw_patch_notes or not raw_patch_notes.strip():
            # Silent update prompt (no official patch notes published by Valve)
            return f"""Ты — ведущий эксперт-аналитик по Counter-Strike 2 (CS2).
Для этого обновления Valve НЕ опубликовали официальные Patch Notes (бесшумный патч / silent update / технический хотфикс).
Однако система PICS зафиксировала изменение файлов в следующих компонентах игры:

{depot_context}

## Твоя задача:
1. **TL;DR** — начни с 1-2 предложений: это технический хотфикс без официального списка изменений.
2. **Анализ затронутых компонентов**:
   - Если затронуты <code>CS2 Binaries (Win64 / Linux64)</code>: объясни, что обновлены основные исполняемые файлы клиента (вероятно, исправление критических крашей, эксплойтов, модулей VAC или утечек памяти).
   - Если затронут <code>CS2 Dedicated Server</code>: выдели важное предупреждение для администраторов серверов (необходимость обновиться через SteamCMD, иначе клиенты с новой версией не смогут подключиться).
   - Если затронут <code>CS2 Client Content / Content</code>: обновлены игровые ассеты (карты, скины, звуки или локализация).
3. **Оценка важности**:
   - 🔴 Критическое (если затронут Dedicated Server или бинарники, требующие обязательного обновления)
   - 🟡 Среднее
   - 🟢 Минорное

## Правила форматирования:
- Используй ТОЛЬКО Telegram HTML: <b>жирный</b>, <i>курсив</i>, <code>код</code>
- НЕ используй Markdown (**, ##, ```, - списки)
- Для списков используй символы ▸ или • в начале строки
- Переносы строк — обычные переводы строки
- Максимум 1200 символов, строго по делу, без лишней воды"""

        # Regular update with patch notes + check for undocumented changes
        return f"""Ты — ведущий эксперт-аналитик по Counter-Strike 2 (CS2).
Проанализируй patch notes обновления CS2 и сопоставь их с изменившимися компонентами игры.
Создай структурированную сводку на русском языке в формате Telegram HTML.

## Официальные Patch Notes (Steam BB-code):
{raw_patch_notes}

{depot_context}

## Инструкции:
1. **TL;DR** — начни с 1-2 предложений: в чём главная суть этого обновления.
2. **Категории** — разбей изменения на секции с иконками:
   - 🎮 Геймплей
   - 🗺 Карты
   - 🛡 Анти-чит / VAC
   - 🎨 Косметика / Армори
   - 🔊 Звук
   - 🖥 Интерфейс
   - 🌐 Сеть / Серверы
   - ⚙️ Прочее
   (используй только релевантные категории, не включай пустые)
3. **🔍 Недокументированные изменения**:
   Внимательно сравни текст Patch Notes с разделом "Изменённые компоненты игры (Depot Changes)".
   Если в депо изменились файлы, о которых ничего прямо не сказано в тексте (например, в тексте только правки карт, но обновились CS2 Dedicated Server или CS2 Binaries):
   - ОБЯЗАТЕЛЬНО добавь блок:
     🔍 <b>Недокументированные изменения:</b>
     • Укажи, какие именно файлы/депо затронуты вопреки молчанию Valve (бинарники клиента, серверная часть).
     • Объясни, что это значит (вероятно, скрытые правки движка/крашей, античит или сетевой протокол).
     • Для администраторов серверов укажи, требуется ли обновление серверов.
4. **Важность** — в конце укажи общую оценку:
   - 🔴 Критическое (меняет мету/геймплей или ломает серверы)
   - 🟡 Среднее (заметные улучшения)
   - 🟢 Минорное (мелкие правки, багфиксы)

## Правила форматирования:
- Используй ТОЛЬКО Telegram HTML: <b>жирный</b>, <i>курсив</i>, <code>код</code>, <a href="url">ссылка</a>
- НЕ используй Markdown (**, ##, ```, - списки)
- НЕ используй теги <h1>, <h2>, <h3>, <p>, <br>, <div>, <ul>, <li>, <ol>
- Для списков используй символы ▸ или • в начале строки
- Переносы строк — обычные переводы строки
- Максимум 2000 символов
- Если patch notes на английском — переведи всё на русский"""

    def _build_depot_context(
        self,
        manifest_changes: dict[str, str] | None,
    ) -> str:
        """Build depot change context string for the prompt."""
        if not manifest_changes:
            return ""

        lines = ["## Изменённые компоненты игры (Depot Changes):"]

        for depot_id_str, manifest_id in manifest_changes.items():
            try:
                depot_id = int(depot_id_str)
                name = CS2_DEPOT_NAMES.get(depot_id, f"Depot {depot_id}")
                lines.append(f"- {name} (ID: {depot_id}): новый manifest {manifest_id}")
            except ValueError:
                lines.append(f"- Depot {depot_id_str}: manifest {manifest_id}")

        return "\n".join(lines)

    # ─── Depot Diff Formatting ───

    def _format_depot_diff_html(self, manifest_changes: dict[str, str]) -> str:
        """Format depot changes as Telegram HTML for the message."""
        lines = []
        for depot_id_str in manifest_changes:
            try:
                depot_id = int(depot_id_str)
                name = CS2_DEPOT_NAMES.get(depot_id, f"Depot {depot_id}")
                lines.append(f"  📦 <b>{name}</b>")
            except ValueError:
                lines.append(f"  📦 <b>Depot {depot_id_str}</b>")

        return "\n".join(lines) if lines else ""

    # ─── Output Sanitization ───

    def _sanitize_telegram_html(self, text: str) -> str:
        """
        Clean AI output to ensure valid Telegram HTML.

        Telegram only supports: <b>, <i>, <u>, <s>, <code>, <pre>, <a>,
        <tg-spoiler>, <tg-emoji>, <blockquote>.
        Everything else must be stripped.
        """
        # Remove Markdown artifacts the AI might have included
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Bold markdown ** → already have <b> tags from prompt
        text = text.replace("**", "")
        text = text.replace("__", "")

        # Remove unsupported HTML tags (keep only Telegram-safe ones)
        allowed_tags = {"b", "i", "u", "s", "code", "pre", "a", "tg-spoiler"}

        def _clean_tag(m: re.Match) -> str:
            full = m.group(0)
            tag_name = m.group(1).lower().lstrip("/")
            # Handle tags with attributes (like <a href="...">)
            if " " in tag_name:
                tag_name = tag_name.split()[0]
            if tag_name in allowed_tags:
                return full
            return ""

        text = re.sub(r"<(/?\w[\w-]*)(?:\s[^>]*)?>", _clean_tag, text)

        # Remove code block markers (```lang ... ```)
        text = re.sub(r"```\w*\n?", "", text)

        # Normalize excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

        # Telegram message limit safety (leave room for the rest of the message)
        max_length = 2500
        if len(text) > max_length:
            cut = text.rfind("\n", 0, max_length)
            if cut > max_length * 0.6:
                text = text[:cut].rstrip()
            else:
                text = text[:max_length]
            text += "\n\n<i>…продолжение по ссылке</i>"

        return text

    def _fallback_analysis(self, raw_patch_notes: str | None) -> UpdateAnalysis:
        """Fallback: basic BB-code → HTML formatting without AI."""
        if not raw_patch_notes:
            return UpdateAnalysis(
                summary_html="<i>Официальные patch notes не опубликованы (бесшумный патч / технический хотфикс).</i>"
            )

        from app.utils.formatting import format_steam_patchnotes_html

        formatted = format_steam_patchnotes_html(raw_patch_notes)
        return UpdateAnalysis(summary_html=formatted)
