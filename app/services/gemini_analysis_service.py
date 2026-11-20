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

    MODEL = "gemini-3.5-flash"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-3.5-flash",
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
        language: str = "ru",
    ) -> UpdateAnalysis:
        """
        Analyze official patch notes and actual Git Diff from GameTracking-CS2.

        Strictly forbids guessing/hallucinations and produces factual Telegram HTML.
        Supports Russian ('ru') and English ('en').
        """
        depot_diff_html = self._format_depot_diff_html(manifest_changes) if manifest_changes else None

        has_patch_notes = bool(raw_patch_notes and raw_patch_notes.strip())
        has_git_diff = bool(git_diff and git_diff.strip())
        has_depots = bool(manifest_changes)

        is_en = (language or "").lower().startswith("en")

        # If neither patch notes nor git diff nor depots are available
        if not has_patch_notes and not has_git_diff and not has_depots:
            summary = (
                "<i>Technical binary update without gameplay, settings or UI changes.</i>"
                if is_en
                else "<i>Техническое обновление исполняемых файлов без изменений в геймплее, настройках и интерфейсе.</i>"
            )
            return UpdateAnalysis(
                summary_html=summary,
                depot_diff_html=depot_diff_html,
            )

        if not self._client:
            return self._fallback_analysis(raw_patch_notes, depot_diff_html, git_diff, language=language)

        try:
            depot_context = self._build_depot_context(manifest_changes)
            prompt = self._build_prompt(
                raw_patch_notes=raw_patch_notes,
                depot_context=depot_context,
                git_diff=git_diff,
                patch_version=patch_version,
                language=language,
            )

            # Call Gemini Flash with fallback across stable active models
            models_to_try = [self.model]
            for fallback_name in (
                "gemini-3.5-flash-lite",
                "gemini-3.5-flash",
                "gemini-3.6-flash",
                "gemini-3.8-flash",
                "gemini-flash-latest",
            ):
                if fallback_name not in models_to_try:
                    models_to_try.append(fallback_name)

            response = None
            used_model = self.model
            last_err = None

            for model_name in models_to_try:
                for attempt in range(2):
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
                        err_str = str(model_err)
                        await logger.awarning(
                            "gemini_model_attempt_failed",
                            model=model_name,
                            attempt=attempt + 1,
                            error=err_str,
                        )
                        if "503" in err_str or "429" in err_str:
                            import asyncio
                            await asyncio.sleep(1.0)
                            continue
                        break
                if response and response.text:
                    break

            if not response or not response.text:
                if last_err:
                    raise last_err
                await logger.awarning("gemini_empty_response")
                return self._fallback_analysis(raw_patch_notes, depot_diff_html, git_diff)

            ai_text = response.text.strip()
            summary_html = self._sanitize_telegram_html(ai_text)

            usage = getattr(response, "usage_metadata", None)
            prompt_tokens = getattr(usage, "prompt_token_count", None) if usage else None
            candidate_tokens = getattr(usage, "candidates_token_count", None) if usage else None
            total_tokens = getattr(usage, "total_token_count", None) if usage else None

            await logger.ainfo(
                "gemini_analysis_complete",
                model=used_model,
                input_patch_len=len(raw_patch_notes) if raw_patch_notes else 0,
                input_diff_len=len(git_diff) if git_diff else 0,
                output_len=len(summary_html),
                prompt_tokens=prompt_tokens,
                candidate_tokens=candidate_tokens,
                total_tokens=total_tokens,
            )

            return UpdateAnalysis(
                summary_html=summary_html,
                depot_diff_html=depot_diff_html,
                raw_response=ai_text,
            )

        except Exception as e:
            await logger.aerror("gemini_analysis_failed", error=str(e), exc_info=True)
            result = self._fallback_analysis(raw_patch_notes, depot_diff_html, git_diff)
            result.error = str(e)
            return result

    # ─── Prompt Engineering ───

    def _build_prompt(
        self,
        raw_patch_notes: str | None = None,
        depot_context: str | None = None,
        git_diff: str | None = None,
        patch_version: str | None = None,
        language: str = "ru",
    ) -> str:
        """Construct the prompt using strict anti-hallucination rules."""
        is_en = (language or "").lower().startswith("en")

        if is_en:
            version_header = f"Update version (steam.inf): {patch_version}\n" if patch_version else ""
            patch_notes_section = (
                f"### 1. Official Valve Patch Notes:\n{raw_patch_notes}\n"
                if (raw_patch_notes and raw_patch_notes.strip())
                else "### 1. Official Valve Patch Notes:\n(No official patch notes available — technical/silent update)\n"
            )
            diff_section = (
                f"### 2. Actual Git Diff from GameTracking-CS2:\n{git_diff}\n"
                if (git_diff and git_diff.strip())
                else "### 2. Actual Git Diff from GameTracking-CS2:\n(No public file changes detected)\n"
            )
            depot_section = f"\n{depot_context}\n" if depot_context else ""
            undocumented_instructions = ""
            if depot_context and not git_diff:
                undocumented_instructions = """
🔍 Undocumented Changes (Depot Changes):
If game depots contain modified files not mentioned in official notes, highlight the affected components.
"""
            return f"""You are a top-tier Counter-Strike 2 technical analyst and dataminer for an English-language community channel. You write stylish, clear, engaging, and concise patch breakdowns for ordinary players while preserving all juicy details from the datamine.
{version_header}
Input data:
1. Official Valve patch notes (may be absent for technical/silent patches).
2. Real Git Diff of modified game files from the GameTracking-CS2 repository.

YOUR GOAL:
Produce an ideal patch breakdown for players. The text must read smoothly and engagingly in natural gaming English, without unnecessary technical clutter, while highlighting all critical, interesting, and juicy facts.

CORE RULES:
1. GAME MODES & TERMINOLOGY:
   - Use standard CS2 community terms: Retakes, Workshop, Premier, Deathmatch, Arms Race, Wingman.

2. CONFIGS & CONVARS (NO TECHNICAL CLUTTER):
   - FORBIDDEN to overload readers with config file paths (e.g. gamemode_retakecasual.cfg) or raw console variable names (e.g. mp_freezetime, mp_round_restart_delay, mp_death_drop_taser).
   - Explain the essence and exact numbers in plain English!
     Example: "In Retakes, reduced round freeze time (from 7 to 5s) and post-round delay (from 5 to 3s)."
     Example: "Workshop maps can now configure whether players drop the Zeus x27 upon death."

3. BULLET FORMATTING:
   - Format each point with a bullet and bold descriptive title:
     • <b>Summary title:</b> detailed explanation in natural English.

4. DATAMINED FINDINGS ("Game File Discoveries"):
   - Put all hidden changes in game resources that aren't mentioned in Valve's official text:
     * Archive animations & assets (if pak01 summary or diff updates 3rd-person draw/reload animations — specify the count of animations, graphs, and affected weapons, e.g. 151 animations).
     * Bot behavior & tactics (if scripts/ai/ or .kv3 files update bot logic for Retakes — describe the new tactics: CT defuse/push, T hide around bomb).
     * Engine configs & netcode (e.g. in gameinfo.gi — explain: server spam protection, parallel interpolation).
     * Graphics & physics (e.g. Parallax Occlusion Mapping, frost/weapon heat mechanics).
     * Missing icons or textures.
     * FACTUAL ACCURACY & TIMELINE: Describe only what genuinely changed in the files. NEVER invent future tournament dates or guess unannounced events if the date has passed.

5. WORKSHOP & SCRIPTING:
   - If changes exist for map makers (Map Scripting / Entities / Precache / VScript), put them into «🛠 <b>Workshop & Scripting:</b>». If none, omit this section completely.

6. IN DEVELOPMENT:
   - Create «🔮 <b>In Development:</b>» EXCLUSIVELY if genuine prototypes or leaks of unreleased content are found (new weapons like LAR, knives, new maps, unannounced game modes).
   - STRICTLY FORBIDDEN to write about build timestamps, compilation dates, or compiler strings in *_strings.txt.
   - If there are no leaks of unreleased content, DO NOT CREATE this section.

7. FORMATTING FOR TELEGRAM:
   - FORBIDDEN to add an overall update title (e.g. "CS2 Update: ...") or welcome intro. Start directly with the first section!
   - Use ONLY allowed HTML tags: <b>bold</b>, <i>italic</i>, <code>code</code>. No markdown!

RESPONSE STRUCTURE:

If official patch notes EXIST:
🎯 <b>Key Highlights:</b>
• <b>...:</b> ...

🔎 <b>Game File Discoveries:</b>
• <b>...:</b> ...

🛠 <b>Workshop & Scripting:</b> (only if API / map scripting changes exist)
• <b>...:</b> ...

🔮 <b>In Development:</b> (only if leaks of unreleased weapons/knives/maps exist)
• <b>...:</b> ...

If NO official patch notes:
First line:
<i>No official patch notes yet</i>

🔎 <b>Game File Discoveries:</b>
• <b>...:</b> ...

🔮 <b>In Development:</b> (if leaks exist)
• <b>...:</b> ...

If only binary recompile without gameplay/settings/UI changes:
<i>Technical binary update without gameplay, settings or UI changes.</i>
{undocumented_instructions}
INPUT DATA:
{patch_notes_section}
{diff_section}
{depot_section}
"""

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

        return f"""Ты — автор качественного Telegram-канала по Counter-Strike 2. Ты пишешь стильные, понятные, интересные и лаконичные разборы обновлений для обычных игроков, сохраняя при этом все важные детали из датамайна.
{version_header}
На вход ты получаешь:
1. Официальный патчноут от Valve (может отсутствовать, если патч технический / «бесшумный»).
2. Реальный Git Diff измененных файлов игры из репозитория GameTracking-CS2.

ТВОЯ ЗАДАЧА:
Сделать идеальный разбор обновления для игроков. Текст должен читаться легко и с интересом, без загромождения техническим мусором, но со всеми важными и сочными фактами.

ГЛАВНЫЕ ПРАВИЛА:
1. ТЕРМИНОЛОГИЯ И РЕЖИМЫ (НЕ ПЕРЕВОДИ НАЗВАНИЯ РЕЖИМОВ):
   - Используй привычные игрокам названия: Retakes (НЕ «ретейки» и НЕ «перехват»), Мастерская или Workshop (НЕ «мастерская карт»), Premier, Deathmatch, Arms Race, Wingman.

2. КОНФИГИ И ПЕРЕМЕННЫЕ (БЕЗ ТЕХНИЧЕСКОГО МУСОРА):
   - КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО нагружать читателя названиями файлов конфигураций (например, gamemode_retakecasual.cfg) и сырыми именами консольных переменных (вроде mp_freezetime, mp_round_restart_delay, mp_death_drop_taser).
   - Описывай суть и точные цифры человеческим языком!
     Например: «В режиме Retakes сократили время заморозки перед раундом (с 7 до 5 секунд) и задержку между раундами (с 5 до 3 секунд)».
     Или: «Для карт Мастерской разрешили настраивать выпадение электрошокера Zeus при гибели игрока».

3. СТРУКТУРИРОВАНИЕ ПУНКТОВ:
   - Каждый пункт оформляй через буллит со смысловым заголовком жирным:
     • <b>Краткая суть:</b> подробное пояснение живым русским языком.

4. НАХОДКИ ИЗ ДАТАМАЙНА («Не вошло в патчноут» / «Находки в файлах игры»):
   - Помещай сюда все скрытые изменения в ресурсах игры, которых нет в официальном тексте Valve:
     * Частицы и визуальные эффекты (файлы .vpcf_c, particles/ — например, реакция огня молотова под дымом, таяние снега, закалка металлов, эффекты взрывов).
     * Анимации оружия и персонажей (файлы .vnmclip_c, animation/ — обязательно указывай точное действие оружия, например «медленная/тихая перезарядка AWP reload_silent_awp», осмотр, доставание).
     * Звуки и музыкальные наборы (.vsnd_c, soundevents/ — новые наборы музыки Monstercat, звуки шагов, рикошеты).
     * Новые предметы, магазин и турниры (из items_game, items_event_store.js, csgo_russian.txt — сортировка команд по посеву в магазине, новые наклейки, пропуск зрителя, монеты).
     * Превью и интерфейс (файлы panorama/images/ — например, новые скриншоты/превью карт de_cbble, de_inferno в меню выбора).
     * Конфиги режимов и правила (например, сокращение времени разминки с 90 до 60 секунд, условия старта раунда).
     * Поведение и тактика ботов (в scripts/ai/ — тактика в Retakes, обезвреживание C4).
     * Сетевые настройки и движок (gameinfo.gi, convars).
     * ФАКТИЧЕСКАЯ ТОЧНОСТЬ И ХРОНОЛОГИЯ: Описывай только то, что реально изменилось в файлах. НИКОГДА не додумывай от себя фразы вроде «предстоящий турнир» или «разработчики готовятся к будущему событию», если событие уже завершено или дата прошла.

5. СКРИПТЫ И API ДЛЯ КАРТОДЕЛОВ («Мастерская и скрипты»):
   - Если в патчноуте или diff есть изменения для создателей карт и скриптов (Map Scripting / Entities / Precache / VScript), выдели их в отдельный блок «🛠 <b>Мастерская и скрипты:</b>». Если таких изменений нет — не создавай этот блок.

6. В РАЗРАБОТКЕ («В разработке»):
   - Создавай блок «🔮 <b>В разработке:</b>» ИСКЛЮЧИТЕЛЬНО если в файлах обнаружены явные прототипы и утечки *еще не вышедшего контента*: новое оружие (винтовка LAR, новое оружие ближнего боя), новые ножи, совершенно новые карты или неанонсированные режимы игры.
   - СТРОЖАЙШЕ ЗАПРЕЩЕНО писать о служебных таймстампах компиляции, датах сборки бинарных файлов (engine2, hammer, csgocfg) и строках компилятора в *_strings.txt.
   - Если масштабных утечек нового невыпущенного контента нет — НЕ СОЗДАВАЙ блок «В разработке». Добавление иконок и текстур для уже вышедших предметов или сувениров относится к «Находкам в файлах игры».

7. ФОРМАТИРОВАНИЕ ДЛЯ TELEGRAM:
   - КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО добавлять общий заголовок обновления (например, «Обновление CS2: 1.41.9.6») или вводные приветственные фразы («Valve выпустили свежий патч...»). Начинай сразу с первого раздела!
   - Используй ТОЛЬКО разрешенные теги: <b>жирный</b>, <i>курсив</i>, <code>код</code>. Никаких markdown ** или #!

СТРУКТУРА ОТВЕТА (НАШ ФИРМЕННЫЙ СТИЛЬ):

Если официальный патчноут ЕСТЬ:
🧰 <b>Дополненный патчноут:</b>
• <b>...:</b> ...

🕵️ <b>Не вошло в патчноут (Датамайн):</b>
• <b>...:</b> ...

🛠 <b>Мастерская и скрипты:</b> (только при наличии изменений API / карт / скриптов)
• <b>...:</b> ...

🔮 <b>В разработке:</b> (только если в файлах найдены утечки скинов, брелоков, оружия или карт)
• <b>...:</b> ...

Если официального патчноута НЕТ:
Первая строка:
<i>Официального списка изменений пока нет</i>

🔎 <b>По анализу файлов игры:</b>
• <b>...:</b> ...

🔮 <b>В разработке:</b> (если есть утечки)
• <b>...:</b> ...

Если в патче совсем нет изменений в интерфейсе, геймплее, звуках, строках или прототипах (только компиляция бинарников) — напиши ровно:
<i>Техническое обновление исполняемых файлов без изменений в геймплее, настройках и интерфейсе.</i>
{undocumented_instructions}
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

        # Strip redundant AI title/intro headers if present (e.g. "Обновление CS2: 1.41.9.6" or "CS2 Update: ...")
        text = re.sub(
            r"^(?:(?:⚡|🔄)?\s*(?:Обновление\s+CS2|CS2\s+Update)[^\n]*\n+|(?:Вышло\s+[^\n]*обновление|A\s+new\s+CS2\s+update\s+is\s+live)[^\n]*\n+)+",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

        # Telegram message limit safety (Telegram allows up to 4096 chars)
        max_length = 3800
        if len(text) > max_length:
            cut = text.rfind("\n", 0, max_length)
            if cut > max_length * 0.6:
                text = text[:cut].rstrip()
            else:
                text = text[:max_length]
            text += "\n\n<i>…продолжение по ссылке</i>"

        return text

    async def generate_x_thread(
        self,
        analysis_en: str,
        patch_version: str | None = None,
    ) -> list[str]:
        """
        Generate an adaptively sized X (Twitter) thread using Gemini Flash.
        Determines thread size based on update magnitude:
        - Minor/hotfix: 1-2 body tweets.
        - Moderate: 2-4 body tweets.
        - Huge/Major: 4-7 body tweets (covering all gameplay, maps, and juicy datamines).
        Returns a list of clean body tweet strings (without intro or outro).
        """
        if not self._client or not analysis_en or not analysis_en.strip():
            return []

        prompt = f"""You are the social media director for a top Counter-Strike 2 news channel on X (Twitter).
Your task is to convert this English patch breakdown into engaging, concise body tweets for an X thread.

Update Version: {patch_version or "N/A"}

English Patch Breakdown:
{analysis_en}

TASK & SIZING GUIDELINES:
1. Assess the magnitude of the update:
   - Minor fix / small hotfix: Generate 1 to 2 body tweets.
   - Moderate update: Generate 2 to 4 body tweets.
   - Massive / Major overhaul / Operation: Generate 4 to 7 body tweets.
2. Content completeness:
   - Do NOT omit real facts, numbers, or datamined discoveries. Retain all major gameplay, weapon, map, and technical changes from the breakdown without cutting corners.
3. Formatting Rules:
   - Write in crisp, authentic CS2 gaming English.
   - Each tweet MUST be self-contained and UNDER 250 characters.
   - Use bold or emoji bullet points (e.g. "🎯 Inferno: ...", "🔎 Datamined: ...").
   - DO NOT include thread numbering like [1/4] (our Python publisher handles that).
   - DO NOT include an intro tweet ("CS2 update is live") or outro tweet ("join Telegram") — provide ONLY the body content tweets!
   - Separate each tweet with three dashes on a new line:
---

Output ONLY the tweets separated by ---:"""

        try:
            models_to_try = [self.model]
            for fallback_name in (
                "gemini-3.5-flash-lite",
                "gemini-3.5-flash",
                "gemini-3.6-flash",
                "gemini-3.8-flash",
                "gemini-flash-latest",
            ):
                if fallback_name not in models_to_try:
                    models_to_try.append(fallback_name)

            for model_name in models_to_try:
                try:
                    resp = await self._client.aio.models.generate_content(
                        model=model_name,
                        contents=prompt,
                    )
                    if resp and resp.text:
                        raw_parts = resp.text.split("---")
                        tweets = [p.strip() for p in raw_parts if p.strip()]
                        valid_tweets = [t for t in tweets if len(t) > 10]
                        if valid_tweets:
                            return valid_tweets[:8]
                except Exception as e:
                    await logger.awarning("gemini_x_thread_failed", model=model_name, error=str(e))
                    continue
        except Exception as e:
            await logger.awarning("gemini_x_thread_generation_error", error=str(e))

        return []

    def _fallback_analysis(
        self,
        raw_patch_notes: str | None,
        depot_diff_html: str | None = None,
        git_diff: str | None = None,
        language: str = "ru",
    ) -> UpdateAnalysis:
        """Fallback when Gemini API fails."""
        is_en = (language or "").lower().startswith("en")
        if not raw_patch_notes:
            if git_diff and git_diff.strip():
                summary = (
                    "<i>No official Valve patch notes. File changes detected in GameTracking-CS2, but automated AI analysis is temporarily unavailable.</i>"
                    if is_en
                    else "<i>Официальный патчноут от Valve отсутствует. Зафиксированы изменения файлов в GameTracking-CS2, но автоматический AI-анализ временно недоступен.</i>"
                )
            else:
                summary = (
                    "<i>No official patch notes published (silent patch / technical hotfix).</i>"
                    if is_en
                    else "<i>Официальные patch notes не опубликованы (бесшумный патч / технический хотфикс).</i>"
                )
            return UpdateAnalysis(
                summary_html=summary,
                depot_diff_html=depot_diff_html,
            )

        from app.utils.formatting import format_steam_patchnotes_html

        formatted = format_steam_patchnotes_html(raw_patch_notes)
        return UpdateAnalysis(
            summary_html=formatted,
            depot_diff_html=depot_diff_html,
        )
