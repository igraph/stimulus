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

from stimulus.errors import NoSuchTypeError

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

    unknown_types: Counter[str]
    """Dictionary that counts how many times we have seen an unknown type
    so we can figure out which ones need to be prioritized.
    """

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)
        self.functions = []
        self.unknown_types = Counter()

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
            # TODO(ntamas): maybe move this logic to the type descriptor into
            # a declare_c_argument() method?
            try:
                param_type_desc = self.get_type_descriptor(param.type)
                param_type = param_type_desc.get_c_type(param.mode)
                by_ref = param_type_desc.is_passed_by_reference
            except NoSuchTypeError:
                param_type = "void"
                by_ref = True
                self.unknown_types[param.type] += 1

            if param_type is not None:
                if by_ref:
                    # Argument is always passed by reference, but it gains a
                    # "const" modifier if it is used as a purely input argument --
                    # except when it is "void*" because everyone does all sorts of
                    # nasty things with void pointers
                    param_type += "*"
                    if param.is_input and not param.is_output and param_type != "void*":
                        param_type = f"const {param_type}"
                else:
                    # Argument is passed by value by default, but it needs to
                    # become a pointer if it is to be used in output or in-out mode
                    if param.is_output:
                        param_type += "*"

                args.append(f"{param_type} {param.name}")

        return_type_desc = self.get_type_descriptor(func_desc.return_type)
        return_type = return_type_desc.get_c_type()

        if return_type is None:
            raise NoSuchTypeError(
                func_desc.return_type,
                message=f"{func_desc.name} declares a return value that has no corresponding C type",
            )

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
        write()
        write("int main() {")

        # Turn off the GCC warning about deprecated declarations because we
        # also want to check those
        write()
        write("#if defined(__GNUC__)")
        write("#  pragma GCC diagnostic push")
        write('#  pragma GCC diagnostic ignored "-Wdeprecated-declarations"')
        write("#endif")
        write()

        write(checks)

        write()
        write("#if defined(__GNUC__)")
        write("#  pragma GCC diagnostic pop")
        write("#endif")

        write()
        write('    printf("Everything OK!");')
        write("    return 0;")
        write("}")

        if self.unknown_types:
            self.log.info("Most common types that were not known to the type system:")
            for type, count in self.unknown_types.most_common(10):
                self.log.info(f"  {type} ({count})")
