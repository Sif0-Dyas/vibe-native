"""The app's version, read from pyproject.toml -- the one place it is written.

At runtime ``vibenative.__version__`` reads the same number back through the
installed distribution's metadata (importlib.metadata), which is how a frozen
build knows it too: the spec bundles that metadata. The build tools use this
module instead, because they must stamp the version pyproject says *now*, and
refuse to build if the installed metadata has fallen behind it.

    python tools/version.py        # prints it
"""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def pyproject_version() -> str:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


if __name__ == "__main__":
    print(pyproject_version())
