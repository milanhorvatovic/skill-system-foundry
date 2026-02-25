"""Shared error categorization and formatted output for validators."""

from .constants import ERROR_SYMBOLS, LEVEL_FAIL, LEVEL_WARN, LEVEL_INFO


def categorize_errors(errors):
    """Split errors into (fails, warns, infos) lists by prefix."""
    fails = [e for e in errors if e.startswith(LEVEL_FAIL)]
    warns = [e for e in errors if e.startswith(LEVEL_WARN)]
    infos = [e for e in errors if e.startswith(LEVEL_INFO)]
    return fails, warns, infos


def print_error_line(error):
    """Print a single error with the appropriate symbol prefix."""
    prefix = error.split(":")[0]
    symbol = ERROR_SYMBOLS.get(prefix, "?")
    print(f"  {symbol} {error}")


def print_summary(fails, warns, infos):
    """Print the final summary line with counts."""
    print(
        f"Results: {len(fails)} failures, {len(warns)} warnings, {len(infos)} info"
    )
