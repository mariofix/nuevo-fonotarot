"""Logging helpers for the nuevo-fonotarot application.

Logging is configured Django-style via the ``LOGGING`` key in each Config
class in ``config.py``.  The dictionary is passed to
:func:`logging.config.dictConfig` during application startup in
:func:`nuevo_fonotarot.flask_app.create_flask`.

Selecting a logger
------------------
Use :func:`get_logger` anywhere in the codebase to obtain a logger::

    from nuevo_fonotarot.log import get_logger

    # Module-scoped — recommended for view files and helpers.
    # The logger name is e.g. 'nuevo_fonotarot.content.views' and inherits
    # level/handler from the 'nuevo_fonotarot' root logger in LOGGING.
    logger = get_logger(__name__)

    # Root application logger ('nuevo_fonotarot') — useful in scripts or
    # places where a module name is not meaningful.
    logger = get_logger()

    # Arbitrary named logger — must be listed in LOGGING["loggers"] if you
    # want custom level/handler settings; otherwise inherits from root.
    logger = get_logger("nuevo_fonotarot.payments")

All loggers whose name starts with ``nuevo_fonotarot`` automatically
inherit the level and handlers configured under the ``"nuevo_fonotarot"``
entry in ``LOGGING["loggers"]``.  To silence or amplify a specific
sub-logger, add it explicitly to ``LOGGING["loggers"]`` in ``config.py``.
"""

import logging

__all__ = ["get_logger"]

# The canonical root logger name for the entire application.
_APP_LOGGER = "nuevo_fonotarot"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a configured application logger.

    Args:
        name: Logger name.

              * ``None`` — returns the root application logger
                (``'nuevo_fonotarot'``).
              * Any string — returned as-is via :func:`logging.getLogger`.
                Pass ``__name__`` for module-scoped loggers; they
                automatically inherit configuration from the
                ``'nuevo_fonotarot'`` hierarchy.

    Returns:
        A :class:`logging.Logger` instance.

    Examples::

        # In a view file:
        logger = get_logger(__name__)   # 'nuevo_fonotarot.content.views'

        # Root app logger:
        logger = get_logger()           # 'nuevo_fonotarot'

        # Named sub-logger (add to LOGGING dict to customise):
        logger = get_logger("nuevo_fonotarot.payments")
    """
    return logging.getLogger(name or _APP_LOGGER)
