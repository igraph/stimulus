"""Code generator classes that are meant for debugging purposes only.

The classes in this module are not really "code generators" in the traditional
sense; they consume the loaded functions and type definitions and print various
pieces of information based on them, but they do not produce any runnable code.
Typically, they are used from the command line as follows::

    $ stimulus -f functions.yaml -t types.yaml -l DebugListTypes
"""

from collections import Counter
from functools import partial
from textwrap import dedent
from typing import IO, List, Sequence

from .base import SingleBlockCodeGenerator
from .utils import create_indentation_function

__all__ = ("ListTypesCodeGenerator",)

indent = create_indentation_function("    ")


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


class FunctionSpecificationValidator(SingleBlockCodeGenerator):
    """Dummy code generator that simply prints C functions that call the
    original C functions from igraph. This file can then be compiled with a
    C++ compiler to validate whether the function specifications are correct
    when linked with igraph.
    """

    functions: List[str]
    """List to collect the names of all the functions that were matched by
    the generator.
    """

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)
        self.functions = []

    def generate_preamble(self, inputs: Sequence[str], output: IO[str]) -> None:
        write = partial(print, file=output)

        write("#include <igraph.h>\n")
        write("#include <cstdio>")
        write("#include <type_traits>\n")

    def generate_function(self, name: str, output: IO[str]) -> None:
        write = partial(print, file=output)

        args: List[str] = []

        func_desc = self.get_function_descriptor(name)
        for param in func_desc.iter_parameters():
            args.append(param.name)

        return_type_desc = self.get_type_descriptor(func_desc.return_type)
        return_type = return_type_desc.get_c_type()

        args_str = ", ".join(args)
        write(f"{return_type} generated_{name}({args_str});")

        self.functions.append(name)

    def generate_epilogue(self, inputs: Sequence[str], output: IO[str]) -> None:
        write = partial(print, file=output)

        checks = "\n".join(
            dedent(
                f"""\
                static_assert(
                    std::is_same<
                        decltype({name}),
                        decltype(generated_{name})
                    >::value,
                    "{name} prototype mismatch"
                );"""
            )
            for name in self.functions
        )
        checks = indent(checks)
        write(f'\nvoid main() {{\n{checks}\n\n    printf("Everything OK!");\n}}')
