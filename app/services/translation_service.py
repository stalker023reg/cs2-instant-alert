"""
CS2 Instant Alert — Translation Service.

Translates patch notes from English to Russian using DeepL API.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from app.core.logging import get_logger

logger = get_logger("system")


class TranslationService:
    """Translates text using DeepL API (Free tier: 500k chars/month)."""

    def __init__(self, api_key: str | None = None) -> None:
        self._translator = None

        # Handle Pydantic SecretStr objects from DI container
        actual_key = api_key
        if actual_key is not None and hasattr(actual_key, 'get_secret_value'):
            actual_key = actual_key.get_secret_value()

        if actual_key:
            try:
                import deepl
                self._translator = deepl.Translator(actual_key)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"DeepL init failed: {e}")

    @property
    def is_available(self) -> bool:
        return self._translator is not None

    async def translate_to_russian(self, text: str) -> str:
        """
        Translate English text to Russian.

        Returns original text if translation fails or DeepL is not configured.
        Preserves HTML tags by using DeepL's tag_handling feature.
        """
        if not self._translator or not text.strip():
            return text

        try:
            # Run blocking DeepL call in thread pool
            result = await asyncio.to_thread(
                self._translator.translate_text,
                text,
                source_lang="EN",
                target_lang="RU",
                tag_handling="html",
                preserve_formatting=True,
            )
            translated = str(result)
            
            # DeepL sometimes inserts extra newlines around parentheses and brackets
            # when using HTML tag handling. Clean these up aggressively.
            import re
            # Remove newlines immediately before or after parentheses/brackets
            translated = re.sub(r'\s*\n\s*\)', ')', translated)
            translated = re.sub(r'\(\s*\n\s*', '(', translated)
            translated = re.sub(r'\s*\n\s*\]', ']', translated)
            translated = re.sub(r'\[\s*\n\s*', '[', translated)
            # Remove newlines inside <a> tags (DeepL sometimes breaks link text across lines)
            translated = re.sub(
                r'(<a\b[^>]*>)(.*?)(</a>)',
                lambda m: m.group(1) + m.group(2).replace('\n', ' ') + m.group(3),
                translated,
                flags=re.DOTALL,
            )
            
            await logger.ainfo(
                "patch_notes_translated",
                original_len=len(text),
                translated_len=len(translated),
            )
            return translated

        except Exception as e:
            await logger.awarning("translation_failed", error=str(e))
            return text
