"""Conventions for repository-local custom checks."""

_LANGUAGES = {"python": "py", "bash": "sh"}


def custom_script_path(check_id: str, language: str) -> str:
    """Return the conventional script path for a custom check."""
    module_name = check_id.replace("-", "_")
    extension = _LANGUAGES[language]
    return f".prec/checks/{check_id}/{module_name}.{extension}"


def custom_script_paths(check_id: str) -> tuple[str, ...]:
    """Return all supported conventional script paths for a custom check."""
    return tuple(custom_script_path(check_id, language) for language in _LANGUAGES)
