"""Code generators for an experimental generated Python interface of igraph."""

from functools import lru_cache
from typing import Callable, IO, List, Optional, Sequence, Set

from stimulus.errors import CodeGenerationError, NoSuchTypeError

from .base import SingleBlockCodeGenerator
from .utils import create_indentation_function


indent = create_indentation_function("  ")


@lru_cache(maxsize=128)
def _get_ctypes_arg_type_from_c_arg_type(c_type: str):
    # Strip "const" from the front
    c_type = c_type.strip()
    while c_type.startswith("const "):
        c_type = c_type[6:].strip()

    # Replace pointer asterisks
    wrap_counter = 0
    while c_type.endswith("*"):
        c_type = c_type[:-1].strip()
        wrap_counter += 1

    while wrap_counter > 0:
        c_type = f"POINTER({c_type})"
        wrap_counter -= 1

    return c_type


class PythonCTypesCodeGenerator(SingleBlockCodeGenerator):
    """Code generator that generates argument and return value specifications
    of each igraph function using the Python ctypes module.

    This generator generates a Python code snippet that can be inserted into
    a Python source file, assuming that the following assumptions hold:

    * the Python source file contains a variable named ``_lib`` that refers to
      igraph's C shared library as loaded by ``ctypes``

    * it also has a callable named ``handle_igraph_error_t`` that takes an
      igraph error code and raises an approprate exception if the error code
      is nonzero (and returns ``None`` otherwise)

    * all the C data types used in the functions are present in the Python
      namespace, aliased to the appropriate ctypes types
    """

    enum_types: Set[str]
    lines: List[str]

    def generate_preamble(self, inputs: Sequence[str], output: IO[str]) -> None:
        self.enum_types = set()
        self.lines = []
        return super().generate_preamble(inputs, output)

    def generate_function(self, name: str, output: IO[str]) -> None:
        self.lines.append("")
        try:
            self._generate_function(name, self.lines.append)
        except CodeGenerationError as ex:
            self.lines.append(f"# {name}: {ex!r}")

    def _generate_function(self, name: str, write: Callable[[str], None]) -> None:
        # Check types
        self.check_types_of_function(name)

        # Get function specification
        spec = self.get_function_descriptor(name)

        # Construct Python return type
        return_type = self.get_type_descriptor(spec.return_type)
        py_return_type: Optional[str] = (
            return_type.get("CTYPES_RETURN_TYPE") or return_type.get_c_type()
        )
        if not py_return_type:
            raise NoSuchTypeError(
                spec.return_type,
                message=f"No ctypes return type known for abstract type {spec.return_type}",
            )

        # Remember the type if it is an enum type
        if return_type.is_enum:
            self.enum_types.add(py_return_type)

        # Construct Python argument types in the ctypes layer
        py_arg_types: List[str] = []
        for parameter in spec.iter_parameters():
            if parameter.is_deprecated:
                continue

            param_type = self.get_type_descriptor(parameter.type)
            c_arg_type = param_type.declare_c_function_argument(mode=parameter.mode)
            if not c_arg_type:
                # This argument is not present in the C function calls
                continue

            py_arg_type = _get_ctypes_arg_type_from_c_arg_type(c_arg_type)
            py_arg_types.append(py_arg_type)

            # Remember the type if it is an enum type
            if param_type.is_enum:
                self.enum_types.add(py_arg_type)

        py_arg_types_joined = ", ".join(py_arg_types)

        write(f"{name} = _lib.{name}")
        write(f"{name}.restype = {py_return_type}")
        write(f"{name}.argtypes = [{py_arg_types_joined}]")

    def generate_epilogue(self, inputs: Sequence[str], output: IO[str]) -> None:
        write = output.write

        if self.enum_types:
            write("# Set up aliases for all enum types\n")
            write("\n")
            for enum_type in sorted(self.enum_types):
                write(f"{enum_type} = c_int\n")
            write("\n")

        write("# Add argument and return types for functions imported from igraph\n")
        write("\n".join(self.lines))
        write("\n")

        return super().generate_epilogue(inputs, output)
