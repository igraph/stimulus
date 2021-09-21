from abc import abstractmethod, ABCMeta
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, IO, Iterable, List, Optional, Tuple

from stimulus.parser import Parser

__all__ = ("CodeGenerator", "CodeGeneratorBase")


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
    def load_function_rules_from_file(self, filename: str) -> None:
        """Loads function specifications from the input file with the given name.

        Parameters:
            filename: the name of the input file
        """
        raise NotImplementedError

    @abstractmethod
    def load_function_rules_from_object(self, obj: Dict[str, Any]) -> None:
        """Loads function specifications from the given object. The object is
        typically parsed from a specification file, although it can also come
        from other sources.

        Parameters:
            obj: the object to load the specifications from
        """
        raise NotImplementedError

    @abstractmethod
    def load_type_rules_from_file(self, filename: str) -> None:
        """Loads type specifications from the input file with the given name.

        Parameters:
            filename: the name of the input file
        """
        raise NotImplementedError

    @abstractmethod
    def load_type_rules_from_object(self, obj: Dict[str, Any]) -> None:
        """Loads type specifications from the given object. The object is
        typically parsed from a specification file, although it can also come
        from other sources.

        Parameters:
            obj: the object to load the specifications from
        """
        raise NotImplementedError


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


class CodeGeneratorBase(CodeGenerator):
    """Base class for code generator implementations."""

    name: str
    func: OrderedDict[str, Any]
    types: OrderedDict[str, Any]

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

        self.func = OrderedDict()
        self.types = OrderedDict()

        self._deps_cache = {}
        self._ignore_cache = {}
        self._param_cache = {}

    def load_function_rules_from_file(self, filename: str) -> None:
        with open(filename) as fp:
            specs = Parser().parse(fp)
        self.load_function_rules_from_object(specs)

    def load_function_rules_from_object(self, obj: Dict[str, Any]) -> None:
        self._preprocess_function_rules(obj)
        self.func.update(obj)

    def load_type_rules_from_file(self, filename: str) -> None:
        with open(filename) as fp:
            specs = Parser().parse(fp)
        self.load_type_rules_from_object(specs)

    def load_type_rules_from_object(self, obj: Dict[str, Any]) -> None:
        self.types.update(obj)

    def generate(self, inputs: Iterable[str], output: IO[str]) -> None:
        self.append_inputs(inputs, output)
        for name, spec in self.func.items():
            self.generate_function(name, output)

    def append_inputs(self, inputs: Iterable[str], output: IO[str]):
        """Appends the contents of the given input files to the given output
        stream.

        Parameters:
            inputs: the input files to append
            output: the output stream to append the files to
        """
        for input in inputs:
            contents = Path(input).read_text()
            output.write(contents)

    @abstractmethod
    def generate_function(self, name: str, out_fp: IO[str]):
        raise NotImplementedError

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

    def _get_function_spec(self, name: str) -> Dict[str, Any]:
        return self.func[name]

    @staticmethod
    def _preprocess_function_rules(specs: Dict[str, Any]):
        for name, spec in specs.items():
            # The default return type is 'ERROR'
            if "RETURN" not in spec:
                spec["RETURN"] = "ERROR"

            if "FLAGS" in spec:
                flags = spec["FLAGS"]
                if isinstance(flags, str):
                    spec["FLAGS"] = [flag.strip() for flag in flags.split(",")]
            else:
                spec["FLAGS"] = []

    def _parse_parameter_specification(self, name: str) -> Dict[str, ParamSpec]:
        param_spec_str = self._get_function_spec(name).get("PARAMS")
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
        dep_spec_str = self._get_function_spec(name).get("DEPS")
        deps = dep_spec_str.split(",") if dep_spec_str else []

        deps = [item.strip().split("ON", 1) for item in deps]
        deps = [[dd.strip() for dd in item] for item in deps]
        deps = [[item[0]] + item[1].split(" ", 1) for item in deps]
        deps = [[dd.strip() for dd in item] for item in deps]

        return {str(name): tuple(values) for name, *values in deps}

    def _should_ignore_function(self, name: str) -> bool:
        """Returns whether the function with the given name should be ignored
        by this code generator.

        Parameters:
            name: the name of the function

        Returns:
            whether the function should be ignored by this code generator
        """
        spec = self._get_function_spec(name)
        tokens = spec.get("IGNORE", "").split(",")
        return any(token.strip() == self.name for token in tokens)
