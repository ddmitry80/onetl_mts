from typing import Generic, TypeVar

from ordered_set import OrderedSet

from onetl.base import PathProtocol, SizedPathProtocol

T = TypeVar("T", bound=PathProtocol)


class FileSet(OrderedSet[T], Generic[T]):  # noqa: WPS600
    """
    Ordered set of pathlib-like objects.

    It has all the methods of generic set (e.g. ``add``, ``difference``, ``intersection``),
    as well as list (e.g. ``append``, ``index``, ``[]``).

    It also has a ``total_size`` helper method.
    """

    @property
    def total_size(self) -> int:
        """
        Get total size (in bytes) of files in the set

        Examples
        --------

        .. code:: python

            from onetl.impl import LocalPath
            from onet.core import FileSet

            file_set = FileSet({LocalPath("/some/file"), LocalPath("/some/another.file")})

            assert file_set.total_size == 1_000_000  # in bytes
        """

        return sum(file.stat().st_size for file in self if isinstance(file, SizedPathProtocol) and file.exists())
