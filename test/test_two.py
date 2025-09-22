import os
from pathlib import Path


def test_two() -> None:
    """Create a file that should not be collected by archive action."""
    path = Path(os.environ["TOX_ENV_DIR"]) / "log" / "popen-gw0"
    path.mkdir(parents=True, exist_ok=True)
    (path / "foo.txt").touch()
