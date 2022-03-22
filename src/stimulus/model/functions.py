from dataclasses import dataclass, field
from deepmerge import always_merger
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    OrderedDict,
    Set,
    Tuple,
)

from .base import DescriptorMixin
from .parameters import ParamSpec
from .utils import camelcase

__all__ = ("FunctionDescriptor",)


@dataclass
class FunctionDescriptor(Mapping[str, Any], DescriptorMixin):
    """Dataclass that describes a single function for which we can generate
    related code in a code generator.
    """

    name: str

    _obj: Dict[str, Any] = field(default_factory=dict)
    _parameters: Optional[OrderedDict[str, ParamSpec]] = None
    _param_order: List[str] = field(default_factory=list)

    flags: Set[str] = field(default_factory=set)
    ignored_by: Set[str] = field(default_factory=set)
    return_type: str = "ERROR"

    def __getitem__(self, key: str) -> Any:
        return self._obj[key]

    def __iter__(self):
        return iter(self._obj)

    def __len__(self):
        return len(self._obj)

    @property
    def is_deprecated(self) -> bool:
        """Returns whether the function is deprecated."""
        return self.has_flag("deprecated")

    @property
    def is_internal(self) -> bool:
        """Returns whether the function is internal (i.e. should not be exported
        in the public namespace of the generated higher-level interface.
        """
        return self.has_flag("internal")

    @property
    def parameters(self) -> OrderedDict[str, ParamSpec]:
        if self._parameters is None:
            self._parameters = self._parse_parameter_specifications()
            self._update_parameter_order()
        return self._parameters

    def get_name_in_generated_code(self, language: str) -> str:
        """Returns the proposed name of the function in code generated for the
        given language.
        """
        lang_key = f"NAME-{language}"
        result = self._obj.get(lang_key) or self._obj.get("NAME")
        if result is None:
            if language == "R":
                return self.name[7:]
            elif language == "Java":
                return camelcase(self.name[7:])
            else:
                return self.name
        else:
            return result

    def has_flag(self, flag: str) -> bool:
        """Checks whether the function descriptor has the given flag, in a
        case-insensitive manner.
        """
        return flag.lower() in self.flags

    @property
    def has_output_parameter(self) -> bool:
        """Returns whether the function has at least one parameter that is
        designated as an output or in-out parameter.
        """
        return any(param.is_output for param in self.parameters.values())

    @property
    def has_primary_output_parameter(self) -> bool:
        """Returns whether the function has at least one parameter that is
        explicitly marked as being a primary output or in-out parameter.
        """
        return any(param.is_primary for param in self.iter_output_parameters())

    @property
    def has_non_primary_output_parameter(self) -> bool:
        """Returns whether the function has at least one parameter that is
        explicitly marked as being a primary output or in-out parameter.
        """
        return any(not param.is_primary for param in self.iter_output_parameters())

    def iter_input_parameters(self, *, reorder: bool = False) -> Iterable[ParamSpec]:
        """Iterates over the input and in-out parameters of this function.

        Parameters:
            reorder: when `False`, iterates over the parameters of this function
                in the order they were _defined_, which should match the ordering
                in C. When `True`, iterates over the parameters in the preferred
                order as specified by `PARAM_ORDER`; this matches the order they
                should appear in the higher level interface. The two are typically
                identical but sometimes they are not.
        """
        if reorder:
            for name in self._param_order:
                param = self.parameters[name]
                if param.is_input:
                    yield param
        else:
            yield from (param for param in self.parameters.values() if param.is_input)

    def iter_parameters(self, *, reorder: bool = False) -> Iterable[ParamSpec]:
        """Iterates over the parameters of this function.

        Parameters:
            reorder: when `False`, iterates over the parameters of this function
                in the order they were _defined_, which should match the ordering
                in C. When `True`, iterates over the parameters in the preferred
                order as specified by `PARAM_ORDER`; this matches the order they
                should appear in the higher level interface. The two are typically
                identical but sometimes they are not.
        """
        if reorder:
            return (self.parameters[name] for name in self._param_order)
        else:
            return self.parameters.values()

    def iter_output_parameters(self) -> Iterable[ParamSpec]:
        """Iterates over the output and in-out parameters of this function in the
        order they were _defined_.
        """
        return (param for param in self.parameters.values() if param.is_output)

    def iter_primary_output_parameters(self) -> Iterable[ParamSpec]:
        """Iterates over the primary output and in-out parameters of this function in the
        order they were _defined_.
        """
        return (param for param in self.iter_output_parameters() if param.is_primary)

    def iter_reordered_parameters(self) -> Iterable[ParamSpec]:
        """Iterates over the parameters of this function in the order they
        should appear in the argument list of the function for the higher
        level interface. This is different from `iter_parameters()` if the
        `PARAM_ORDER` key is present in the input YAML file.
        """
        return (self.parameters[name] for name in self._param_order)

    def update_from(self, obj: Dict[str, str]) -> None:
        """Updates the function descriptor from an object typically parsed from
        a specification file.

        The rules are as follows:

          - The ``PARAMS`` key from `obj` overwrites the previous parameter
            description.

          - The ``DEPS`` key from `obj` overwrites the previous dependencies.

          - The ``RETURN`` key from `obj` overwrites the previous return type.

          - The ``PARAM_ORDER`` key from `obj` overwrites the previous parameter
            order.

          - THe values from the ``IGNORE`` list are added to the existing list
            of generators that will ignore this function. ``IGNORE`` may also
            be a string, in which case it will be split along commas.

          - The values from the ``FLAGS`` list are merged with the existing
            flags. ``FLAGS`` may also be a string, in which case it will be
            split along commas.

          - The mapping in the ``PARAM_NAMES`` key is merged with the
            existing parameter name mapping.

          - Any other key in `obj` is merged with the existing key-value store.
        """
        if "PARAMS" in obj:
            self._obj["PARAMS"] = ""
            self._parameters = None

        if "DEPS" in obj:
            self._obj["DEPS"] = ""
            self._parameters = None

        if "PARAM_NAMES" in obj:
            self._parameters = None

        if "PARAM_ORDER" in obj:
            self._param_order.clear()
            self._parameters = None

        always_merger.merge(self._obj, obj)

        it = self._parse_as_comma_separated_list("IGNORE")
        self.ignored_by |= set(it)

        it = self._parse_as_comma_separated_list("FLAGS")
        self.flags |= set(flag.lower() for flag in it)

        is_internal = self._parse_as_boolean("INTERNAL")
        if is_internal is not None:
            if is_internal is True:
                self.flags.add("internal")
            else:
                self.flags.discard("internal")

        return_type: str = self._obj.pop("RETURN", "")
        if return_type:
            self.return_type = str(return_type)

    def _parse_dependencies(self) -> Dict[str, Tuple[str, ...]]:
        dep_spec_str = self._obj.get("DEPS")
        deps = dep_spec_str.split(",") if dep_spec_str else []

        deps = [item.strip().split("ON", 1) for item in deps]
        deps = [[dd.strip() for dd in item] for item in deps]
        deps = [[item[0]] + item[1].split(" ", 1) for item in deps]
        deps = [[dd.strip() for dd in item] for item in deps]

        return {str(name): tuple(values) for name, *values in deps}

    def _parse_parameter_specifications(self) -> OrderedDict[str, ParamSpec]:
        params: List[str]

        param_spec_str = self._obj.get("PARAMS")
        param_name_mapping = self._obj.get("PARAM_NAMES")

        if not param_spec_str:
            params = []
        elif isinstance(param_spec_str, str):
            params = param_spec_str.split(",")
        elif hasattr(param_spec_str, "__iter__"):
            params = list(param_spec_str)
        else:
            raise TypeError(
                f"PARAMS must be a string or a list, got {type(param_spec_str)!r}"
            )

        specs = [ParamSpec.from_string(item) for item in params]
        result = OrderedDict((spec.name, spec) for spec in specs)

        for name, deps in self._parse_dependencies().items():
            for dep in deps:
                param = result.get(name)
                if param:
                    param.add_dependency(dep)
                else:
                    raise RuntimeError(
                        f"dependency declared on unknown argument {name!r} of "
                        f"function {self.name!r}"
                    )

        if param_name_mapping:
            for name, new_name in param_name_mapping.items():
                param = result.get(name)
                if param:
                    param.name_override = new_name or None
                else:
                    raise RuntimeError(
                        f"parameter name was overridden for unknown "
                        f"parameter {name!r} of function {self.name!r}"
                    )

        return result

    def _update_parameter_order(self) -> None:
        assert self._parameters is not None

        param_order_str = self._obj.get("PARAM_ORDER")

        if not param_order_str:
            param_order = []
        elif isinstance(param_order_str, str):
            param_order = param_order_str.split(",")
        elif hasattr(param_order_str, "__iter__"):
            param_order = list(param_order_str)
        else:
            raise TypeError(
                f"PARAM_ORDER must be a string or a list, got {type(param_order_str)!r}"
            )

        self._param_order.clear()
        rest_index = -1

        not_seen_params = list(self._parameters.keys())
        for name in param_order:
            name = name.strip()
            if name in not_seen_params:
                self._param_order.append(name)
                not_seen_params.remove(name)
            elif name == "...":
                rest_index = len(self._param_order)
            else:
                raise RuntimeError(
                    f"parameter {name!r} appears twice in PARAM_ORDER for "
                    f"function {self.name!r}"
                )

        if not_seen_params:
            if rest_index < 0:
                rest_index = len(self._param_order)
            self._param_order[rest_index:rest_index] = not_seen_params
