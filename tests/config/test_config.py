import pytest

from prec.config import Check, loads_config
from prec.errors import ConfigError


def load(text: str):  # type: ignore[no-untyped-def]
    return loads_config(text.encode())


def test_empty_config() -> None:
    assert load("version = 1\nchecks = []\n").checks == ()


def test_explicit_custom_script() -> None:
    assert load(
        'version = 1\n[[checks]]\nid = "custom"\nscript = ".prec/checks/custom.py"\n'
    ).checks == (Check(id="custom", script=".prec/checks/custom.py"),)


def test_complete_check_and_defaults() -> None:
    config = load(
        """
version = 1
[[checks]]
id = "ruff"
run = ["ruff", "check", "--", ""]
files = ["*.py"]
exclude = ["vendor/"]
pass_filenames = false
always_run = true
timeout_seconds = 0.5
batch_size = 100
"""
    )
    assert config.checks == (
        Check(
            id="ruff",
            run=("ruff", "check", "--", ""),
            files=("*.py",),
            exclude=("vendor/",),
            pass_filenames=False,
            always_run=True,
            timeout_seconds=0.5,
            batch_size=100,
        ),
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("checks = []", "version: required"),
        ("version = 1", "checks: required"),
        ('version = "1"\nchecks = []', "version: expected integer 1"),
        ("version = 1.0\nchecks = []", "version: expected integer 1"),
        ("version = 2\nchecks = []", "version: expected integer 1"),
        ("version = 1\nchecks = {}", "checks: expected an array"),
        ('version = 1\nchecks = ["bad"]', "checks[0]: expected a table"),
        ('version = 1\n[[checks]]\nrun = ["x"]', "checks[0].id: required"),
        ('version = 1\n[[checks]]\nid = "x"', "exactly one"),
        (
            'version = 1\n[[checks]]\nid = "x"\nrun = ["x"]\nscript = "x"',
            "exactly one",
        ),
        ('version = 1\n[[checks]]\nid = "x"\nscript = "../x"', "repository-relative"),
        ('version = 1\n[[checks]]\nid = "x"\nscript = "."', "repository-relative"),
        ('version = 1\n[[checks]]\nid = "x"\nscript = "bad\\u0000path"', "repository-relative"),
        ('version = 1\n[[checks]]\nid = "Bad"\nrun = ["x"]', "must match"),
        ('version = 1\n[[checks]]\nid = "x"\nrun = []', "array must not be empty"),
        ('version = 1\n[[checks]]\nid = "x"\nrun = [""]', "executable must not be empty"),
        (
            'version = 1\n[[checks]]\nid = "x"\nrun = ["/absolute/x"]',
            "relative to the repository",
        ),
        (
            'version = 1\n[[checks]]\nid = "x"\nrun = ["../outside"]',
            "relative to the repository",
        ),
        (
            'version = 1\n[[checks]]\nid = "x"\nrun = ["x"]\nfiles = []',
            "array must not be empty",
        ),
        (
            'version = 1\n[[checks]]\nid = "x"\nrun = ["x"]\npass_filenames = "no"',
            "expected a boolean",
        ),
        (
            'version = 1\n[[checks]]\nid = "x"\nrun = ["x"]\ntimeout_seconds = 0',
            "positive finite number",
        ),
        (
            'version = 1\n[[checks]]\nid = "x"\nrun = ["x"]\ntimeout_seconds = inf',
            "positive finite number",
        ),
        (
            'version = 1\n[[checks]]\nid = "x"\nrun = ["x"]\nbatch_size = 0',
            "positive integer",
        ),
        ("version = 1\nfile = []\nchecks = []", "unknown field"),
        (
            'version = 1\n[[checks]]\nid = "x"\nrun = ["x"]\nfile = ["*.py"]',
            "did you mean `files`",
        ),
    ],
)
def test_invalid_schema(text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message.replace("[", r"\[").replace("]", r"\]")):
        load(text)


def test_duplicate_toml_key_is_error() -> None:
    with pytest.raises(ConfigError, match="invalid TOML"):
        load("version = 1\nversion = 1\nchecks = []")


def test_duplicate_check_id_is_error() -> None:
    with pytest.raises(ConfigError, match="duplicate check id `x`"):
        load('version = 1\n[[checks]]\nid = "x"\nrun = ["x"]\n[[checks]]\nid = "x"\nrun = ["x"]\n')


def test_invalid_utf8_is_error() -> None:
    with pytest.raises(ConfigError, match="valid UTF-8"):
        loads_config(b"\xff")


def test_toml_boolean_words_are_strings() -> None:
    with pytest.raises(ConfigError, match="expected a boolean"):
        load('version = 1\n[[checks]]\nid = "x"\nrun = ["x"]\npass_filenames = "on"')
