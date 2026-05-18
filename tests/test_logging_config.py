from config import DevelopmentConfig


def test_khipu_provider_logger_is_explicitly_configured():
    loggers = DevelopmentConfig.LOGGING["loggers"]

    for logger_name in ("merchants", "flask_merchants"):
        logger_cfg = loggers[logger_name]
        assert logger_cfg["handlers"] == ["console", "file"]
        assert logger_cfg["level"] == DevelopmentConfig.LOG_LEVEL
        assert logger_cfg["propagate"] is False
