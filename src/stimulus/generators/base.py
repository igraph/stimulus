import re

from abc import abstractmethod, ABCMeta
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from io import StringIO
from logging import Logger
from pathlib import Path
from shutil import copyfileobj
from typing import (
    Any,
    Dict,
    IO,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from stimulus.errors import StimulusError
from stimulus.legacy.parser import Parser as LegacyParser

__all__ = (
    "BlockBasedCodeGenerator",
    "CodeGenerator",
    "CodeGeneratorBase",
    "FunctionDescriptor",
    "InputPlacement",
    "ParamMode",
    "ParamSpec",
    "SingleBlockCodeGenerator",
)


class ParamMode(Enum):
    """Enum representing the modes of function parameters."""

    IN = "in"
    OUT = "out"
    INOUT = "inout"


@dataclass
class ParamSpec:
    """Specification of a single function parameter."""

    name: str
    type: str
    mode: ParamMode = ParamMode.IN
    default: Optional[str] = None

    def as_dict(self) -> Dict[str, str]:
        """Returns a dict representation of the parameter specification."""
        result = {"name": self.name, "mode": self.mode_str, "type": self.type}
        if self.default is not None:
            result["default"] = self.default
        return result

    @property
    def is_input(self) -> bool:
        """Returns whether the function parameter is an input argument."""
        return self.mode in (ParamMode.IN, ParamMode.INOUT)

    @property
    def is_output(self) -> bool:
        """Returns whether the function parameter is an output argument."""
        return self.mode in (ParamMode.OUT, ParamMode.INOUT)

    @property
    def mode_str(self) -> str:
        return str(self.mode.value).upper()


@dataclass
class FunctionDescriptor(Mapping[str, Any]):
    """Dataclass that describes a single function for which we can generate
    related code in a code generator.
    """

    _obj: Dict[str, str] = field(default_factory=dict)

    ignored_by: Set[str] = field(default_factory=set)
    return_type: str = "ERROR"

    def __getitem__(self, key: str) -> Any:
        return self._obj[key]

    def __iter__(self):
        return iter(self._obj)

    def __len__(self):
        return len(self._obj)

    def update_from(self, obj: Dict[str, str]) -> None:
        """Updates the function descriptor from an object typically parsed from
        a specification file.
        """
        self._obj.update(obj)

        ignore: str = obj.get("IGNORE", "")
        if ignore:
            self.ignored_by = set(part.strip() for part in ignore.split(","))

        return_type: str = obj.get("RETURN", "")
        if return_type:
            self.return_type = str(return_type)


class CodeGenerator(metaclass=ABCMeta):
    """Interface specification for code generators."""

    name: str

    @abstractmethod
    def generate(self, inputs: List[str], output: IO[str]) -> None:
        """Generates code from the given input files into the given output
        stream, according to the function and type rules loaded into the
        generator.

        Parameters:
            inputs: the list of input files to process
            output: the output stream to write the generated code into
        """
        raise NotImplementedError

    @abstractmethod
    def load_function_descriptors_from_file(self, filename: str) -> None:
        """Loads function descriptors from the input file with the given name.

        Parameters:
            filename: the name of the input file
        """
        raise NotImplementedError

    @abstractmethod
    def load_function_descriptors_from_object(self, obj: Dict[str, Any]) -> None:
        """Loads function descriptors from the given object. The object is
        typically parsed from a specification file, although it can also come
        from other sources.

        Parameters:
            obj: the object to load the descriptors from
        """
        raise NotImplementedError

    @abstractmethod
    def load_type_descriptors_from_file(self, filename: str) -> None:
        """Loads type descriptors from the input file with the given name.

        Parameters:
            filename: the name of the input file
        """
        raise NotImplementedError

    @abstractmethod
    def load_type_descriptors_from_object(self, obj: Dict[str, Any]) -> None:
        """Loads type descriptors from the given object. The object is
        typically parsed from a specification file, although it can also come
        from other sources.

        Parameters:
            obj: the object to load the descriptors from
        """
        raise NotImplementedError

    @abstractmethod
    def use_logger(self, log: Logger) -> None:
        """Instructs the code generator to log any issues that it finds during
        code generation to the given logger.
        """
        raise NotImplementedError


def _nop(*args, **kwds) -> None:
    pass


class _DummyLogger:
    def __getattr__(self, name: str):
        return _nop


class CodeGeneratorBase(CodeGenerator):
    """Base class for code generator implementations."""

    log: Logger
    name: str
    types: Dict[str, Any]

    _function_descriptors: Dict[str, FunctionDescriptor]

    _deps_cache: Dict[str, Dict[str, Tuple[str, ...]]]
    _ignore_cache: Dict[str, bool]
    _param_cache: Dict[str, Dict[str, ParamSpec]]

    def __init__(self):
        """Constructor."""
        # Set name, note this only works correctly if derived classes always
        # extend it as by prepending the language to the CodeGenerator class
        # name
        self.name = type(self).__name__
        self.name = self.name[0 : len(self.name) - len("CodeGenerator")]

        self.log = _DummyLogger()  # type: ignore

        self._function_descriptors = OrderedDict()
        self.types = OrderedDict()

        self._deps_cache = {}
        self._ignore_cache = {}
        self._param_cache = {}

    def load_function_descriptors_from_file(self, filename: str) -> None:
        specs = self._parse_file(filename)
        self.load_function_descriptors_from_object(specs)

    def load_function_descriptors_from_object(self, obj: Dict[str, Any]) -> None:
        for name, spec in obj.items():
            descriptor = self._function_descriptors.get(name)
            if not descriptor:
                self._function_descriptors[name] = descriptor = FunctionDescriptor()
            descriptor.update_from(spec)

    def load_type_descriptors_from_file(self, filename: str) -> None:
        specs = self._parse_file(filename)
        self.load_type_descriptors_from_object(specs)

    def load_type_descriptors_from_object(self, obj: Dict[str, Any]) -> None:
        self.types.update(obj)

    def use_logger(self, log: Logger) -> None:
        self.log = log

    @abstractmethod
    def generate_function(self, name: str, output: IO[str]) -> None:
        """Processes the function with the given name and generates the
        corresponding output on the output stream.

        This function is _not_ called for functions that are deemed to be
        ignored by `should_ignore_function()`.
        """
        raise NotImplementedError

    def generate_functions_block(self, output: IO[str]) -> None:
        """Generates the part of the output file that contains the generated code
        for functions.
        """
        for name in self.iter_functions():
            self.generate_function(name, output)

    def get_dependencies_for_function(self, name: str) -> Dict[str, Tuple[str, ...]]:
        """Returns a dictionary mapping the names of the parameters of the given
        function to the names of additional parameters they depend on.

        Parameters:
            name: the name of the function

        Returns:
            a dictionary mapping the names of the parameters to their
            dependencies
        """
        result = self._deps_cache.get(name)
        if result is None:
            self._deps_cache[name] = result = self._parse_dependency_specification(name)
        return result

    def get_parameters_for_function(self, name: str) -> Dict[str, ParamSpec]:
        """Returns a dictionary mapping the names of the parameters of the given
        function to their parameter specifications.

        Parameters:
            name: the name of the function

        Returns:
            a dictionary mapping the names of the parameters to their parameter
            specifications
        """
        result = self._param_cache.get(name)
        if result is None:
            self._param_cache[name] = result = self._parse_parameter_specification(name)
        return result

    def iter_functions(self, include_ignored: bool = False) -> Iterable[str]:
        """Iterator that yields the names of the functions in the function
        specification that are _not_ to be ignored by this generator.
        """
        if include_ignored:
            yield from self._function_descriptors.keys()
        else:
            for name in self._function_descriptors:
                if not self.should_ignore_function(name):
                    yield name

    def should_ignore_function(self, name: str) -> bool:
        """Returns whether the function with the given name should be ignored
        by this code generator.

        This function is memoized. Do not override this function; override
        `_should_ignore_function()` instead.

        Parameters:
            name: the name of the function

        Returns:
            whether the function should be ignored by this code generator
        """
        result = self._ignore_cache.get(name)
        if result is None:
            self._ignore_cache[name] = result = self._should_ignore_function(name)
        return result

    def get_function_descriptor(self, name: str) -> FunctionDescriptor:
        return self._function_descriptors[name]

    def _append_inputs(self, inputs: Sequence[str], output: IO[str]) -> None:
        for input in inputs:
            with Path(input).open() as fp:
                copyfileobj(fp, output)

    def _parse_parameter_specification(self, name: str) -> Dict[str, ParamSpec]:
        param_spec_str = self.get_function_descriptor(name).get("PARAMS")
        params = param_spec_str.split(",") if param_spec_str else []
        params = [item.strip().split(" ", 1) for item in params]

        for p in range(len(params)):
            if params[p][0] in ["OUT", "IN", "INOUT"]:
                params[p] = [params[p][0]] + params[p][1].split(" ", 1)
            else:
                params[p] = ["IN", params[p][0]] + params[p][1].split(" ", 1)
            if "=" in params[p][2]:
                params[p] = params[p][:2] + params[p][2].split("=", 1)
        params = [[p.strip() for p in pp] for pp in params]

        return {
            str(name): ParamSpec(
                name=str(name),
                mode=ParamMode(mode.lower()),
                type=str(type),
                default=rest[0] if rest else None,
            )
            for mode, type, name, *rest in params
        }

    def _parse_dependency_specification(self, name: str) -> Dict[str, Tuple[str, ...]]:
        dep_spec_str = self.get_function_descriptor(name).get("DEPS")
        deps = dep_spec_str.split(",") if dep_spec_str else []

        deps = [item.strip().split("ON", 1) for item in deps]
        deps = [[dd.strip() for dd in item] for item in deps]
        deps = [[item[0]] + item[1].split(" ", 1) for item in deps]
        deps = [[dd.strip() for dd in item] for item in deps]

        return {str(name): tuple(values) for name, *values in deps}

    def _parse_file(self, name: str) -> Dict[str, Any]:
        """Parses a generic input file. The extension of the input file decides
        whether to use the legacy ``.def`` parser or a standard YAML parser.
        """
        if name.lower().endswith(".def"):
            with open(name) as fp:
                return LegacyParser().parse(fp)
        else:
            from yaml import safe_load

            with open(name) as fp:
                return safe_load(fp)

    def _should_ignore_function(self, name: str) -> bool:
        """Returns whether the function with the given name should be ignored
        by this code generator.

        Parameters:
            name: the name of the function

        Returns:
            whether the function should be ignored by this code generator
        """
        desc = self.get_function_descriptor(name)
        return self.name in desc.ignored_by


class BlockBasedCodeGenerator(CodeGeneratorBase):
    """Code generator that looks for block markers in input files and replaces
    each block with the corresponding content.

    Block markers are lines that look like this:

        % STIMULUS: block_name %

    where the colon and the whitespace after and before the percent signs are
    optional. Block names may contain alphanumeric characters, underscore and
    dash only.
    """

    _BLOCK_REGEXP = re.compile(r"^\s*%\s*STIMULUS:?\s*(?P<name>[-A-Za-z0-9_]*)\s*%")

    _block_cache: Dict[str, str]

    def __init__(self):
        super().__init__()
        self._block_cache = {}

    def generate(self, inputs: Sequence[str], out: IO[str]) -> None:
        for input in inputs:
            with open(input) as fp:
                for line in fp:
                    if not self._process_marker_line(line, out):
                        out.write(line)

    def _generate_block(self, name: str) -> str:
        """Generates the contents of the block with the given name.

        This function is called once per block; further occurrences of the same
        block are retrieved from the cache.
        """
        handler = getattr(self, f"generate_{name}_block", None)
        if handler is None:
            raise StimulusError(f"Unhandled block in input file: {name}")

        buf = StringIO()
        handler(buf)
        return buf.getvalue()

    def _process_marker_line(self, line: str, out: IO[str]) -> bool:
        """Attempts to process a potential marker line in one of the input files.

        Marker lines are the ones that start with ``% STIMULUS``.

        Returns:
            whether the line was handled. Unhandled files should be forwarded to
            the output as is by the caller.
        """
        match = self._BLOCK_REGEXP.match(line)
        if match:
            block_name = match.group("name") or "functions"
            block = self._block_cache.get(block_name)
            if block is None:
                self._block_cache[block_name] = block = self._generate_block(block_name)
            out.write(block)
            return True
        else:
            return False


class InputPlacement(Enum):
    """Enum describing the possible placements of input files in a
    single-block code generator.
    """

    PREAMBLE = "preamble"
    EPILOGUE = "epilogue"


class SingleBlockCodeGenerator(CodeGeneratorBase):
    """Code generator that generates all functions in a single block and then
    puts the content of all input files before or after them.
    """

    def __init__(self, input_placement: InputPlacement = InputPlacement.PREAMBLE):
        super().__init__()
        self._input_placement = input_placement

    def generate(self, inputs: Sequence[str], output: IO[str]) -> None:
        self.generate_preamble(inputs, output)
        self.generate_functions_block(output)
        self.generate_epilogue(inputs, output)

    def generate_epilogue(self, inputs: Sequence[str], output: IO[str]) -> None:
        """Processes the input files with the given names and generates the
        epilogue of the output, i.e. the part that gets printed _after_ the
        processed functions.
        """
        if self._input_placement is InputPlacement.EPILOGUE:
            self._append_inputs(inputs, output)

    def generate_preamble(self, inputs: Sequence[str], output: IO[str]) -> None:
        """Processes the input files with the given names and generates the
        preamble of the output, i.e. the part that gets printed _before_ the
        processed functions.
        """
        if self._input_placement is InputPlacement.PREAMBLE:
            self._append_inputs(inputs, output)
