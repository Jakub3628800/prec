import subprocess
from pathlib import Path

import pytest

_CHECK = Path(__file__).parents[2] / ".prec/checks/end-of-file/end_of_file.py"


@pytest.mark.parametrize(
    ("content", "returncode"),
    [
        (b"", 0),
        (b"content\n", 0),
        (b"content\r\n", 0),
        (b"content", 1),
        (b"content\n\n", 1),
    ],
)
def test_end_of_file_check(tmp_path: Path, content: bytes, returncode: int) -> None:
    candidate = tmp_path / "candidate.txt"
    candidate.write_bytes(content)

    result = subprocess.run([_CHECK, candidate], capture_output=True, check=False)

    assert result.returncode == returncode
