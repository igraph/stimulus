from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

__all__ = ("ParamMode", "ParamSpec")


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
    dependencies: List[str] = field(default_factory=list)

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
