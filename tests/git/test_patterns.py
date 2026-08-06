import pytest

from prec.git.patterns import PatternError, PatternSet, filter_paths, validate_pattern


@pytest.mark.parametrize(
    ("pattern", "matching", "not_matching"),
    [
        ("*.py", ["a.py", "src/a.py", ".hidden.py"], ["a.pyc"]),
        ("/a.py", ["a.py"], ["src/a.py"]),
        ("src/*.py", ["src/a.py"], ["a.py", "src/lib/a.py"]),
        ("src/**/*.py", ["src/a.py", "src/lib/a.py"], ["tests/a.py"]),
        ("vendor/", ["vendor/a.c", "vendor/lib/a.c"], ["src/vendor/a.c"]),
        ("file?.[ch]", ["file1.c", "filex.h"], ["file10.c"]),
        ("#file", ["#file"], ["file"]),
    ],
)
def test_pattern_conformance(pattern: str, matching: list[str], not_matching: list[str]) -> None:
    matcher = PatternSet.compile((pattern,))
    assert all(matcher.matches(path) for path in matching)
    assert not any(matcher.matches(path) for path in not_matching)


def test_include_then_exclude() -> None:
    paths = ("a.py", "vendor/a.py", "a.txt")
    assert filter_paths(paths, ("*.py",), ("vendor/",)) == ("a.py",)


@pytest.mark.parametrize("pattern", ["", "!generated/**", "../x", "x/../y", "x\0y"])
def test_invalid_patterns(pattern: str) -> None:
    with pytest.raises(PatternError):
        validate_pattern(pattern)


def test_pattern_order_does_not_change_union() -> None:
    paths = ("a.py", "src/a.ts", "readme.md")
    first = filter_paths(paths, ("*.py", "*.ts"), ())
    second = filter_paths(paths, ("*.ts", "*.py"), ())
    assert first == second
