from pathlib import Path
from typing import Dict, Optional, Union

from stimulus.model import DocstringProvider

__all__ = ("DocstringProvider", "FolderBasedDocstringProvider")


class FolderBasedDocstringProvider:
    """Docstring provider that returns docstrings from files in a given folder
    on the filesystem.
    """

    _root: Path
    """Root folder that contains the files with the docstrongs."""

    _cache: Optional[Dict[str, str]] = None

    def __init__(self, root: Union[str, Path]):
        self._root = Path(root)

    def __call__(self, name: str) -> Optional[str]:
        if not self._cache:
            self._cache = self._populate_cache()

        return self._cache.get(name)

    def _populate_cache(self) -> Dict[str, str]:
        return {
            filename.stem: filename.read_text().strip()
            for filename in self._root.glob("*.txt")
        }
