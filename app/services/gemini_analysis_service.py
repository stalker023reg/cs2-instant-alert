"""
CS2 Instant Alert — Gemini AI Analysis Service.

Analyzes patch notes and real git diffs from GameTracking-CS2 using Google Gemini Flash
to generate structured, hallucination-free summaries in Russian.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.utils.depot_filter import CS2_DEPOT_NAMES, filter_depots, format_depots_html

logger = get_logger("system")


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
    Analyzes CS2 updates using Google Gemini Flash.
    Strictly follows anti-hallucination guidelines.
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
        git_diff: str | None = None,
        patch_version: str | None = None,
    ) -> UpdateAnalysis:
        """
        Analyze official patch notes and actual Git Diff from GameTracking-CS2.

        Strictly forbids guessing/hallucinations and produces factual Telegram HTML.
        """
        depot_diff_html = self._format_depot_diff_html(manifest_changes) if manifest_changes else None

        has_patch_notes = bool(raw_patch_notes and raw_patch_notes.strip())
        has_git_diff = bool(git_diff and git_diff.strip())
        has_depots = bool(manifest_changes)

        # If neither patch notes nor git diff nor depots are available
        if not has_patch_notes and not has_git_diff and not has_depots:
            summary = "<i>Техническое обновление исполняемых файлов без изменений в геймплее, настройках и интерфейсе.</i>"
            return UpdateAnalysis(
                summary_html=summary,
                depot_diff_html=depot_diff_html,
            )

        if not self._client:
            return self._fallback_analysis(raw_patch_notes, depot_diff_html)

        try:
            depot_context = self._build_depot_context(manifest_changes)
            prompt = self._build_prompt(
                raw_patch_notes=raw_patch_notes,
                depot_context=depot_context,
                git_diff=git_diff,
                patch_version=patch_version,
            )

            # Call Gemini Flash with fallback across models if high demand
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
                return self._fallback_analysis(raw_patch_notes, depot_diff_html)

            ai_text = response.text.strip()
            summary_html = self._sanitize_telegram_html(ai_text)

            await logger.ainfo(
                "gemini_analysis_complete",
                model=used_model,
                input_patch_len=len(raw_patch_notes) if raw_patch_notes else 0,
                input_diff_len=len(git_diff) if git_diff else 0,
                output_len=len(summary_html),
            )

            return UpdateAnalysis(
                summary_html=summary_html,
                depot_diff_html=depot_diff_html,
                raw_response=ai_text,
            )

        except Exception as e:
            await logger.aerror("gemini_analysis_failed", error=str(e), exc_info=True)
            result = self._fallback_analysis(raw_patch_notes, depot_diff_html)
            result.error = str(e)
            return result

    # ─── Prompt Engineering ───

    def _build_prompt(
        self,
        raw_patch_notes: str | None = None,
        depot_context: str | None = None,
        git_diff: str | None = None,
        patch_version: str | None = None,
    ) -> str:
        """Construct the prompt using strict anti-hallucination rules."""
        version_header = f"Версия обновления (steam.inf): {patch_version}\n" if patch_version else ""

        patch_notes_section = (
            f"### 1. Официальный патчноут от Valve:\n{raw_patch_notes}\n"
            if (raw_patch_notes and raw_patch_notes.strip())
            else "### 1. Официальный патчноут от Valve:\n(Официальный патчноут отсутствует — техническое обновление / бесшумный патч)\n"
        )

        diff_section = (
            f"### 2. Реальный Git Diff из репозитория GameTracking-CS2:\n{git_diff}\n"
            if (git_diff and git_diff.strip())
            else "### 2. Реальный Git Diff из репозитория GameTracking-CS2:\n(В публичных ресурсах изменений файлов не обнаружено)\n"
        )

        depot_section = f"\n{depot_context}\n" if depot_context else ""

        undocumented_instructions = ""
        if depot_context and not git_diff:
            undocumented_instructions = """
🔍 Недокументированные изменения (Depot Changes):
Если в депо изменились файлы, о которых ничего не сказано в тексте, отметь затронутые компоненты.
"""

        return f"""Ты — старший технический аналитик и датамайнер обновлений Counter-Strike 2.
{version_header}
На вход ты получаешь:
1. Официальный патчноут от Valve (может отсутствовать, если патч технический / бесшумный патч).
2. Реальный Git Diff измененных файлов игры из репозитория GameTracking-CS2 (консольные переменные, файлы скриптинга .d.ts, интерфейс Panorama UI, локализация, протобафы).

Твоя задача — составить точный, профессиональный разбор обновления на русском языке для Telegram-канала.

СТРОГИЕ ПРАВИЛА (ЗАПРЕТ НА ГАЛЛЮЦИНАЦИИ):
1. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО выдумывать изменения, которых нет во входных данных. Никогда не пиши общие фразы вроде «вероятно, обновлены сигнатуры VAC», «устранены утечки памяти», «исправлены эксплойты или геометрия карт», если это прямо не следует из предоставленного кода/текста.
2. Запрещено использовать слова-догадки: «вероятно», «скорее всего», «как правило», «возможно». Опирайся только на факты из diff и патчноута.
3. Сохраняй точные названия новых или измененных классов, методов, событий и консольных команд (ConVars) в моноширинном формате (<code>код</code>), указывая их значения по умолчанию, если они видны в диффе.

ФОРМАТ ОТВЕТА:
Используй чистую верстку для Telegram (используй ТОЛЬКО теги <b>жирный</b>, <i>курсив</i>, <code>код</code>).
Раздели отчет на блоки (выводи блок только если для него есть реальные данные во входных материалах):

🧰 <b>Основной патчноут и скриптинг</b>
• Перевод официального патчноута на русский язык.
• Если в диффе есть изменения point_script.d.ts (или других API), подробно и структурированно перечисли новые классы, методы, свойства, события и исправления типов (как дополнение к патчноуту).

🕵️ <b>Не вошло в патчноут (Датамайнинг)</b>
• <b>Консоль и настройки:</b> новые или измененные команды из convars.txt / commands.txt и за что они отвечают (исходя из их описания в диффе).
• <b>Интерфейс (Panorama UI):</b> что именно изменилось в верстке/стилях (.css / .xml / .js) — например, размеры панелей, цвета, новые элементы меню или HUD.
• <b>Локализация и ресурсы:</b> новые текстовые строки или упоминания контента.
{undocumented_instructions}
Если официального патчноута нет, а в Git Diff не нашлось изменений в командах, UI, скриптах или локализации — напиши ровно одно предложение:
Техническое обновление исполняемых файлов без изменений в геймплее, настройках и интерфейсе.

ВХОДНЫЕ ДАННЫЕ:
{patch_notes_section}
{diff_section}
{depot_section}
"""

    def _build_depot_context(self, manifest_changes: dict[str, Any] | None) -> str:
        """Build depot change context string for the prompt."""
        if not manifest_changes:
            return ""

        lines = ["## Изменённые компоненты игры (Depot Changes):"]

        for depot_id_str, val in manifest_changes.items():
            try:
                depot_id = int(depot_id_str)
                name = CS2_DEPOT_NAMES.get(depot_id, f"Depot {depot_id}")
                if isinstance(val, dict):
                    old_m = val.get("old_manifest")
                    new_m = val.get("new_manifest")
                    lines.append(f"- {name} (ID: {depot_id}): {old_m} -> {new_m}")
                else:
                    lines.append(f"- {name} (ID: {depot_id}): новый manifest {val}")
            except ValueError:
                lines.append(f"- Depot {depot_id_str}: manifest {val}")

        return "\n".join(lines)

    def _format_depot_diff_html(self, manifest_changes: dict[str, Any]) -> str:
        """Format depot changes as Telegram HTML for the message."""
        filtered_depots, tech_count = filter_depots(manifest_changes)
        if not filtered_depots and not tech_count:
            return ""
        return format_depots_html(filtered_depots, tech_count)

    # ─── Output Sanitization ───

    def _sanitize_telegram_html(self, text: str) -> str:
        """
        Clean AI output to ensure valid Telegram HTML.
        Telegram only supports: <b>, <i>, <u>, <s>, <code>, <pre>, <a>, <tg-spoiler>.
        """
        # Convert markdown bold **text** to <b>text</b>
        text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
        # Convert markdown inline code `code` to <code>code</code>
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

        # Remove markdown headers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

        # Remove unsupported HTML tags (keep only Telegram-safe ones)
        allowed_tags = {"b", "i", "u", "s", "code", "pre", "a", "tg-spoiler"}

        def _clean_tag(m: re.Match) -> str:
            full = m.group(0)
            tag_name = m.group(1).lower().lstrip("/")
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

        # Telegram message limit safety
        max_length = 2500
        if len(text) > max_length:
            cut = text.rfind("\n", 0, max_length)
            if cut > max_length * 0.6:
                text = text[:cut].rstrip()
            else:
                text = text[:max_length]
            text += "\n\n<i>…продолжение по ссылке</i>"

        return text

    def _fallback_analysis(
        self,
        raw_patch_notes: str | None,
        depot_diff_html: str | None = None,
    ) -> UpdateAnalysis:
        """Fallback: basic BB-code -> HTML formatting without AI."""
        if not raw_patch_notes:
            return UpdateAnalysis(
                summary_html="<i>Официальные patch notes не опубликованы (бесшумный патч / технический хотфикс).</i>",
                depot_diff_html=depot_diff_html,
            )

        from app.utils.formatting import format_steam_patchnotes_html

        formatted = format_steam_patchnotes_html(raw_patch_notes)
        return UpdateAnalysis(
            summary_html=formatted,
            depot_diff_html=depot_diff_html,
        )
