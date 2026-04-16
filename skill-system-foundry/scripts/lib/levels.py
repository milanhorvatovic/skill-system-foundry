"""Error-level string constants.

Isolated from ``constants.py`` so that low-level modules
(``yaml_parser``) can import error levels without creating a circular
dependency (``constants`` imports ``yaml_parser`` to parse
``configuration.yaml``).
"""

LEVEL_FAIL = "FAIL"
LEVEL_WARN = "WARN"
LEVEL_INFO = "INFO"
