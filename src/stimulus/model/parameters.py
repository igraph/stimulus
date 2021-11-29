from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

__all__ = ("ParamMode", "ParamSpec")


class ParamMode(Enum):
    """Enum representing the modes of function parameters."""

    IN = "in"
    OUT = "out"
    INOUT = "inout"

    @classmethod
    def is_input(cls, value: "ParamMode") -> bool:
        return value is cls.IN or value is cls.INOUT

    @classmethod
    def is_output(cls, value: "ParamMode") -> bool:
        return value is cls.OUT or value is cls.INOUT


@dataclass
class ParamSpec:
    """Specification of a single function parameter."""

    name: str
    """Name of the parameter in the function signature."""

    type: str
    """Type of the parameter in the function signature.

    This is the "abstract type" of the parameter, which is then mapped to a real
    type both in C and in the host language by the type definition files.
    """

    mode: ParamMode = ParamMode.IN
    """Mode of the parameter (input, output or both)."""

    default: Optional[str] = None
    """Default value of the parameter.

    This is an "abstract" default value, which is then mapped to concrete values
    by the type definition files.
    """

    dependencies: List[str] = field(default_factory=list)
    """List of other parameters that the code generators will need to generate
    code for the in- and out-conversions of this parameter.
    """

    output_name_override: Optional[str] = None
    """Name of the parameter when used as an output and the code generator needs
    to return multiple output parameters to the caller. `None` means that the
    name is the same as the "real" name of the parameter.
    """

    @classmethod
    def from_string(cls, value: str):
        """Constructs a ParamSpec object from its string representation in a
        ``.def`` or ``.yaml`` file.
        """
        parts = value.strip().split(" ", 1)
        if parts[0] not in ("OUT", "IN", "INOUT"):
            parts = ["IN", parts[0]] + parts[1].split(" ", 1)
        else:
            parts = [parts[0]] + parts[1].split(" ", 1)
        if "=" in parts[2]:
            parts = parts[:2] + parts[2].split("=", 1)

        mode, type, name, *rest = [part.strip() for part in parts]
        return ParamSpec(
            name=str(name),
            mode=ParamMode(mode.lower()),
            type=str(type),
            default=rest[0] if rest else None,
        )

    def add_dependency(self, name: str) -> None:
        """Adds a new dependency to this parameter specification."""
        self.dependencies.append(name)

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

    @property
    def name_as_output(self) -> str:
        """Returns the name of the parameter when it is used as an output
        parameter. This can be used by a code generator for a higher-level
        interface when it needs to return multiple output parameters; typically
        this is done by returning a key-value mapping where the key is the
        "output name" of the parameter.
        """
        return self.output_name_override or self.name
