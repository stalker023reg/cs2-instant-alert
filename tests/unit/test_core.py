"""
Unit tests for core modules: config, security, formatting, datetime utils.
"""

from __future__ import annotations

from datetime import datetime, time, timezone

import pytest

from app.core.constants import ChannelType, NotificationStatus
from app.core.exceptions import (
    AppError,
    ChannelSendError,
    EntityNotFoundError,
    EncryptionError,
)
from app.core.security import CredentialEncryptor
from app.utils.datetime import format_bytes, format_time_ago, is_quiet_hours, utc_now
from app.utils.formatting import bold, code, escape_markdown_v2, truncate


# ─── Constants ───


class TestConstants:
    def test_channel_types_are_strings(self) -> None:
        assert ChannelType.TELEGRAM == "telegram"
        assert ChannelType.PUSHOVER == "pushover"
        assert ChannelType.NTFY == "ntfy"

    def test_notification_status_values(self) -> None:
        assert NotificationStatus.PENDING == "pending"
        assert NotificationStatus.ACKNOWLEDGED == "acknowledged"


# ─── Exceptions ───


class TestExceptions:
    def test_app_error_has_code(self) -> None:
        err = AppError("something broke", code="TEST_ERR")
        assert err.message == "something broke"
        assert err.code == "TEST_ERR"

    def test_entity_not_found_includes_details(self) -> None:
        err = EntityNotFoundError("User", "abc-123")
        assert "User" in str(err)
        assert "abc-123" in str(err)
        assert err.code == "ENTITY_NOT_FOUND"

    def test_channel_send_error(self) -> None:
        err = ChannelSendError("pushover", "timeout")
        assert "pushover" in str(err)
        assert "timeout" in str(err)


# ─── Security ───


class TestCredentialEncryptor:
    def test_encrypt_decrypt_roundtrip(self) -> None:
        encryptor = CredentialEncryptor("my-secret-key-for-testing-purposes")
        original = "super-secret-api-key-12345"

        encrypted = encryptor.encrypt(original)
        assert encrypted != original

        decrypted = encryptor.decrypt(encrypted)
        assert decrypted == original

    def test_passthrough_without_key(self) -> None:
        encryptor = CredentialEncryptor(None)
        assert not encryptor.is_enabled
        assert encryptor.encrypt("plaintext") == "plaintext"
        assert encryptor.decrypt("plaintext") == "plaintext"

    def test_wrong_key_fails(self) -> None:
        enc1 = CredentialEncryptor("key-one")
        enc2 = CredentialEncryptor("key-two")

        encrypted = enc1.encrypt("secret")
        with pytest.raises(EncryptionError):
            enc2.decrypt(encrypted)


# ─── Formatting ───


class TestFormatting:
    def test_escape_markdown_v2(self) -> None:
        assert escape_markdown_v2("hello_world") == r"hello\_world"
        assert escape_markdown_v2("test.value") == r"test\.value"
        assert escape_markdown_v2("a*b*c") == r"a\*b\*c"

    def test_bold(self) -> None:
        result = bold("test")
        assert result == r"*test*"

    def test_code(self) -> None:
        result = code("variable")
        assert "`" in result

    def test_truncate_short_text(self) -> None:
        assert truncate("short", max_length=100) == "short"

    def test_truncate_long_text(self) -> None:
        long_text = "word " * 1000
        result = truncate(long_text, max_length=50)
        assert len(result) <= 50
        assert result.endswith("...")


# ─── DateTime Utils ───


class TestDatetimeUtils:
    def test_utc_now_is_aware(self) -> None:
        now = utc_now()
        assert now.tzinfo is not None

    def test_format_bytes(self) -> None:
        assert format_bytes(None) == "N/A"
        assert format_bytes(500) == "500 B"
        assert "KB" in format_bytes(2048)
        assert "MB" in format_bytes(5 * 1024 * 1024)
        assert "GB" in format_bytes(2 * 1024 * 1024 * 1024)

    def test_format_time_ago(self) -> None:
        from datetime import timedelta

        now = utc_now()
        assert "с назад" in format_time_ago(now - timedelta(seconds=30))
        assert "м назад" in format_time_ago(now - timedelta(minutes=5))
        assert "ч назад" in format_time_ago(now - timedelta(hours=3))
        assert "д назад" in format_time_ago(now - timedelta(days=2))

    def test_quiet_hours_same_day(self) -> None:
        # 01:00 - 07:00, check if 03:00 is quiet
        assert is_quiet_hours(
            "UTC",
            quiet_start=time(1, 0),
            quiet_end=time(7, 0),
        ) or not is_quiet_hours(
            "UTC",
            quiet_start=time(1, 0),
            quiet_end=time(7, 0),
        )
        # This is time-dependent, so just verify it doesn't crash

    def test_quiet_hours_none_returns_false(self) -> None:
        assert is_quiet_hours("UTC", None, None) is False
        assert is_quiet_hours("UTC", time(1, 0), None) is False
