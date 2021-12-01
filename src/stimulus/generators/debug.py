"""Code generator classes that are meant for debugging purposes only.

The classes in this module are not really "code generators" in the traditional
sense; they consume the loaded functions and type definitions and print various
pieces of information based on them, but they do not produce any runnable code.
Typically, they are used from the command line as follows::

    $ stimulus -f functions.yaml -t types.yaml -l DebugListTypes
"""

from collections import Counter
from functools import partial
from typing import IO

from .base import SingleBlockCodeGenerator

__all__ = ("ListTypesCodeGenerator",)


class ListTypesCodeGenerator(SingleBlockCodeGenerator):
    """Debugging aid that lists all the types that appear in the function
    definitions.
    """

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)
        self.collected_types: Counter[str] = Counter()

    def generate_function(self, name: str, output: IO[str]) -> None:
        spec = self.get_function_descriptor(name)
        self.collected_types.update(param.type for param in spec.iter_parameters())
        self.collected_types.update((spec.return_type,))

    def generate_functions_block(self, output: IO[str]) -> None:
        super().generate_functions_block(output)
        write = partial(print, file=output)
        for type, count in sorted(self.collected_types.items()):
            write(type, count)
