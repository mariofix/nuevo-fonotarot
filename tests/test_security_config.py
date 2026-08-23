import pytest

from config import TestingConfig, _assert_required_secret_config


def test_testing_config_uses_non_placeholder_secrets() -> None:
    assert TestingConfig.SECRET_KEY == "testing-secret-key"
    assert TestingConfig.SECURITY_PASSWORD_SALT == "testing-password-salt"
    assert TestingConfig.MERCHANTS_KEY == "testing-merchants-key"


def test_assert_required_secret_config_rejects_placeholders() -> None:
    with pytest.raises(RuntimeError, match="SECURITY_PASSWORD_SALT"):
        _assert_required_secret_config(
            {
                "SECRET_KEY": "dev-secret-key-change-me",
                "SECURITY_PASSWORD_SALT": "dev-password-salt-change-me",
                "MERCHANTS_KEY": "dev-merchants-key-change-me",
            }
        )
