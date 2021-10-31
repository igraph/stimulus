from collections import OrderedDict
from dataclasses import dataclass, field
from deepmerge import always_merger
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
)

from .parameters import ParamSpec

__all__ = ("FunctionDescriptor",)


@dataclass
class FunctionDescriptor(Mapping[str, Any]):
    """Dataclass that describes a single function for which we can generate
    related code in a code generator.
    """

    name: str

    _obj: Dict[str, str] = field(default_factory=dict)
    _parameters: Optional[OrderedDict[str, ParamSpec]] = None

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
    def is_internal(self) -> bool:
        """Returns whether the function is internal (i.e. should not be exported
        in the public namespace of the generated higher-level interface.
        """
        return self.has_flag("internal")

    @property
    def parameters(self) -> OrderedDict[str, ParamSpec]:
        if self._parameters is None:
            self._parameters = self._parse_parameter_specifications()
        return self._parameters

    def has_flag(self, flag: str) -> bool:
        """Checks whether the function descriptor has the given flag, in a
        case-insensitive manner.
        """
        return flag.lower() in self.flags

    def iter_parameters(self) -> Iterable[ParamSpec]:
        """Iterates over the parameters of this function in the order they
        were defined.
        """
        return self.parameters.values()

    def update_from(self, obj: Dict[str, str]) -> None:
        """Updates the function descriptor from an object typically parsed from
        a specification file.

        The rules are as follows:

          - The ``PARAMS`` key cannot be overridden; if the function descriptor
            already contains parameters and the new object being merged into it
            also contains one, an error will be thrown.

          - The ``DEPS`` key cannot be overridden; if the function descriptor
            already contains dependencies and the new object being merged into it
            also contains one, an error will be thrown.

          - The ``RETURN`` key from `obj` overwrites the previous return type.

          - THe values from the ``IGNORE`` list are added to the existing list
            of generators that will ignore this function. ``IGNORE`` may also
            be a string, in which case it will be split along commas.

          - The values from the ``FLAGS`` list are merged with the existing
            flags. ``FLAGS`` may also be a string, in which case it will be
            split along commas.

          - Any other key in `obj` is merged with the existing key-value store.
        """
        if "PARAMS" in obj:
            if "PARAMS" in self._obj:
                raise RuntimeError(
                    "PARAMS cannot be overridden in function descriptors"
                )

            self._parameters = None

        if "DEPS" in obj:
            if "DEPS" in self._obj:
                raise RuntimeError("DEPS cannot be overridden in function descriptors")

            self._dependencies = None

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

    def _parse_as_boolean(self, key: str) -> Optional[bool]:
        value = self._obj.pop(key, None)
        if value is None:
            return None
        elif isinstance(value, (int, float)):
            return bool(value)
        elif isinstance(value, str):
            return value.lower() in ("true", "yes", "y")
        else:
            return bool(value)

    def _parse_as_comma_separated_list(self, key: str) -> Iterable[str]:
        value = self._obj.pop(key, None)
        if value is None:
            return ()
        if isinstance(value, str):
            return (part.strip() for part in value.split(","))
        elif hasattr(value, "__iter__"):
            return (part.strip() for part in value)  # type: ignore
        else:
            if key:
                raise RuntimeError(f"{key!r} key must map to a string or a list")
            else:
                raise RuntimeError("key must map to a string or a list")

    def _parse_parameter_specifications(self) -> OrderedDict[str, ParamSpec]:
        param_spec_str = self._obj.get("PARAMS")
        params: List[str]

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
                    # TODO(ntamas): this should be an error as soon as
                    # R-igraph starts depending on igraph 0.9.5
                    print(
                        f"dependency declared on unknown argument {name!r} of "
                        f"function {self.name!r}"
                    )

        return result