"""Code generators for an experimental generated Python interface of igraph."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Dict, IO, List, Optional, Sequence, Set, Tuple

from stimulus.errors import CodeGenerationError, NoSuchTypeError
from stimulus.model.functions import FunctionDescriptor
from stimulus.model.parameters import ParamSpec
from stimulus.model.types import TypeDescriptor

from .base import SingleBlockCodeGenerator
from .utils import create_indentation_function, remove_prefix


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

    # Add c_ prefix if needed
    if c_type in (
        "char",
        "int",
        "float",
        "double",
        "size_t",
        "ssize_t",
        "bool",
        "void",
    ):
        c_type = f"c_{c_type}"

    # Some ctypes types have specific aliases for the single-pointer case
    if wrap_counter > 0 and c_type in ("c_void", "c_char", "c_wchar"):
        wrap_counter -= 1
        c_type = f"{c_type}_p"

    # Wrap the type in POINTER() as many times as needed
    while wrap_counter > 0:
        c_type = f"POINTER({c_type})"
        wrap_counter -= 1

    # c_void should be substituted with None
    if c_type == "c_void":
        c_type = "None"

    return c_type


def _get_python_type_from_type_spec(type_spec: TypeDescriptor) -> Optional[str]:
    return type_spec.get("PY_TYPE")


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

    bitfield_types: Set[str]
    enum_types: Set[str]
    lines: List[str]

    def generate_preamble(self, inputs: Sequence[str], output: IO[str]) -> None:
        self.bitfield_types = set()
        self.enum_types = set()
        self.lines = []
        return super().generate_preamble(inputs, output)

    def generate_function(self, name: str, output: IO[str]) -> None:
        self.lines.append("")
        try:
            self._generate_function(name, self.lines.append)
        except CodeGenerationError as ex:
            self.lines.append(f"# {name}: {ex}")

    def _generate_function(self, name: str, write: Callable[[str], None]) -> None:
        # Check types
        self.check_types_of_function(name)

        # Get function specification
        spec = self.get_function_descriptor(name)

        # Construct Python return type
        return_type = self.get_type_descriptor(spec.return_type)
        py_return_type: Optional[str] = return_type.get("CTYPES_RETURN_TYPE")
        if not py_return_type:
            # Try deriving the ctypes type
            py_return_type = _get_ctypes_arg_type_from_c_arg_type(
                return_type.get_c_type()
            )

        if not py_return_type:
            raise NoSuchTypeError(
                spec.return_type,
                message=f"No ctypes return type known for abstract type {spec.return_type}",
            )

        # Remember the type if it is an enum type or a bitfield type
        if return_type.is_enum:
            self.enum_types.add(py_return_type)
        if return_type.is_bitfield:
            self.bitfield_types.add(py_return_type)

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

            # Remember the type if it is an enum type or a bitfield type
            if param_type.is_enum:
                self.enum_types.add(py_arg_type)
            if param_type.is_bitfield:
                self.bitfield_types.add(py_arg_type)

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

        if self.bitfield_types:
            write("# Set up aliases for all bitfield types\n")
            write("\n")
            for bitfield_type in sorted(self.bitfield_types):
                write(f"{bitfield_type} = c_int\n")
            write("\n")

        write("# Add argument and return types for functions imported from igraph\n")
        write("\n".join(self.lines))
        write("\n")

        return super().generate_epilogue(inputs, output)


@dataclass
class ArgInfo:
    param_spec: ParamSpec
    type_spec: TypeDescriptor

    c_name: str
    py_name: str
    py_type: str

    appears_in_argument_list: bool = False
    default_value: Optional[str] = None

    @classmethod
    def from_param_spec(
        cls, spec: ParamSpec, type_descriptor_getter: Callable[[str], TypeDescriptor]
    ):
        type = type_descriptor_getter(spec.type)

        py_name = spec.name

        # Translate Python reserved keywords
        if py_name in ("from", "in", "lambda"):
            py_name += "_"

        c_name = f"c_{spec.name}"

        py_type = _get_python_type_from_type_spec(type)
        if py_type is None:
            raise CodeGenerationError(f"no Python type known for type: {type.name}")

        result = cls(
            param_spec=spec,
            type_spec=type,
            c_name=c_name,
            py_name=py_name,
            py_type=py_type,
        )

        if not spec.is_deprecated:
            # IN and INOUT arguments will appear in the Python call signature;
            # pure OUT arguments will not
            result.appears_in_argument_list = spec.is_input

        # Map default value to Python
        if spec.default is not None:
            result.default_value = type.translate_default_value(spec.default)
        else:
            result.default_value = None

        return result

    @property
    def name(self) -> str:
        return self.param_spec.name

    def get_input_conversion(self) -> Optional[str]:
        template = self.type_spec.get_input_conversion_template_for(
            self.param_spec.mode,
            default="%C% = %I%" if self.param_spec.is_input else "",
        )
        if not template:
            if not self.param_spec.is_input:
                raise CodeGenerationError(
                    f"Cannot construct an instance of abstract type {self.type_spec.name}"
                )
            else:
                return None
        else:
            # TODO(ntamas): handle DEPS
            return template.replace("%I%", self.py_name).replace("%C%", self.c_name)

    def get_output_conversion(self) -> Optional[str]:
        template = self.type_spec.get_output_conversion_template_for(
            self.param_spec.mode,
            default="%I% = %C%.value" if self.param_spec.is_output else "",
        )
        if not template:
            return None
        else:
            # TODO(ntamas): handle DEPS
            return (
                template.replace("%I%", self.py_name).replace("%C%", self.c_name)
                or None
            )

    def get_python_declaration(self) -> str:
        """Returns the declaration of this argument for the Python function header."""
        return (
            f"{self.py_name}: {self.py_type}"
            if self.default_value is None
            else f"{self.py_name}: {self.py_type} = {self.default_value}"
        )


class PythonCTypesTypedWrapperCodeGenerator(SingleBlockCodeGenerator):
    def generate_function(self, name: str, output: IO[str]) -> None:
        write = output.write

        lines = [""]
        try:
            self._generate_function(name, lines.append)
            lines.append("")
            write("\n".join(lines))
        except CodeGenerationError as ex:
            write(f"\n# {name}: {ex}\n")

    def _generate_function(self, name: str, write: Callable[[str], None]) -> None:
        # Check types
        self.check_types_of_function(name)

        # Get function specification
        spec = self.get_function_descriptor(name)

        # Derive Python name of the function from its C name
        py_name = self._get_python_name(spec)

        # Construct Python arguments
        args = self._process_argument_list(spec)

        # Check whether any default argument precedes non-default arguments.
        # TODO(ntamas): reorder arguments if this happens?
        has_default = False
        for arg_spec in spec.iter_reordered_parameters():
            if arg_spec.is_deprecated or not arg_spec.is_input:
                continue

            if arg_spec.default is None:
                if has_default:
                    raise CodeGenerationError(
                        f"at least one default argument precedes non-default argument {arg_spec.name}"
                    )
            else:
                has_default = True

        # Print function header
        py_return_type, return_arg_names = self._get_return_type_and_args(spec)
        py_args = ", ".join(
            args[arg_spec.name].get_python_declaration()
            for arg_spec in spec.iter_reordered_parameters()
            if args[arg_spec.name].appears_in_argument_list
        )
        write("")
        write(f"def {py_name}({py_args}) -> {py_return_type}:")
        write(f'    """Type-annotated wrapper for ``{spec.name}``."""')

        # Add input conversion calls
        convs = [
            args[param_spec.name].get_input_conversion()
            for param_spec in spec.iter_parameters()
        ]
        convs = [conv for conv in convs if conv]
        if convs:
            write("    # Prepare input arguments")
            for conv in convs:
                write("    " + conv)
            write("")

        write("    # Call wrapped function")
        needs_return_value_from_c_call = "" in return_arg_names
        c_args = ", ".join(
            args[arg_spec.name].c_name for arg_spec in spec.iter_parameters()
        )
        c_call = f"{name}({c_args})"
        if needs_return_value_from_c_call:
            c_call = f"c__result = {c_call}"
        write(f"    {c_call}")

        # Add output conversion calls
        convs = [
            args[param_spec.name].get_output_conversion()
            for param_spec in spec.iter_parameters()
        ]
        convs = [conv for conv in convs if conv]
        if convs:
            write("")
            write("    # Prepare output arguments")
            for conv in convs:
                write("    " + conv)

        if return_arg_names:
            write("")
            write("    # Construct return value")
            if len(return_arg_names) == 1:
                if needs_return_value_from_c_call:
                    var_name = "c__result"
                else:
                    var_name = args[return_arg_names[0]].py_name
                write(f"    return {var_name}")
            else:
                joint_parts = ", ".join(
                    args[name].py_name if name else "c__result"
                    for name in return_arg_names
                )
                write(f"    return {joint_parts}")

    def _get_python_name(self, spec: FunctionDescriptor) -> str:
        return spec.get("NAME") or remove_prefix(spec.name, "igraph_")

    def _get_return_type_and_args(
        self, spec: FunctionDescriptor
    ) -> Tuple[str, List[str]]:
        """Returns the return type of the given function and the names of the
        C arguments from which the output arguments are created.

        An empty string in the returned argument list means that the return
        value of the C function should be converted into the return value of
        the Python function.

        The rules are as follows:

        - The index of each argument marked as OUT appears in the returned list
          of arguments.

        - INOUT parameters are _not_ returned, but it is assumed that the
          function will mutate these arguments in-place.

        - If the function is declared to return with an `ERROR` abstract type,
          it is assumed that the underlying ctypes wrapper handles the error and
          raises appropriate exceptions.

        - If the function is declared to return any other abstract type than
          `ERROR` or `VOID`, the return value itself is _also_ considered and
          -1 is prepended to the list of argument indices.
        """
        arg_names: List[str] = []
        arg_types: List[TypeDescriptor] = []
        arg_type_strs: List[str]

        return_type = self.get_type_descriptor(spec.return_type)
        if return_type.name != "ERROR" and return_type.name != "VOID":
            arg_names.append("")
            arg_types.append(return_type)

        for index, parameter in enumerate(spec.iter_parameters()):
            if not parameter.is_deprecated and not parameter.is_input:
                arg_names.append(parameter.name)
                arg_types.append(self.get_type_descriptor(parameter.type))

        arg_type_strs = []
        for arg_spec in arg_types:
            py_type = _get_python_type_from_type_spec(arg_spec)
            if py_type is None:
                raise CodeGenerationError(
                    f"no Python type known for type: {arg_spec.name}"
                )
            arg_type_strs.append(py_type)

        if not arg_type_strs:
            output_type = "None"
        elif len(arg_type_strs) == 1:
            output_type = arg_type_strs[0]
        else:
            output_type = "Tuple[" + ", ".join(arg_type_strs) + "]"

        return output_type, arg_names

    def _process_argument_list(self, spec: FunctionDescriptor) -> Dict[str, ArgInfo]:
        return {
            param.name: ArgInfo.from_param_spec(param, self.get_type_descriptor)
            for param in spec.iter_parameters()
        }
