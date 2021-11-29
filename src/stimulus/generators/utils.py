"""Helper utility functions for code generators."""

from functools import lru_cache
from textwrap import indent
from typing import Callable


__all__ = ("create_indentation_function",)


@lru_cache(maxsize=32)
def create_indentation_function(indentation: str) -> Callable[[str], str]:
    """Creates a function that indents the given input string with the
    given indentation, except when the input string is empty.
    """

    def func(input: str) -> str:
        return indent(input, indentation) if input else input

    return func
