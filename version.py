import os
from pathlib import Path


here = Path(__file__).parent.resolve()


def get_version():
    if "CI_COMMIT_TAG" in os.environ:
        return os.environ["CI_COMMIT_TAG"]

    version_file = here / "onetl" / "VERSION"
    version = version_file.read_text().strip()  # noqa: WPS410

    build_num = os.environ.get("CI_PIPELINE_IID", "")
    return f"{version}.dev{build_num}"
