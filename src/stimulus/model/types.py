from dataclasses import dataclass, field
from deepmerge import always_merger
from typing import (
    Any,
    Dict,
    Mapping,
)

from stimulus.model.parameters import ParamMode

__all__ = ("TypeDescriptor",)


@dataclass
class TypeDescriptor(Mapping[str, Any]):
    """Dataclass that describes a single type that is used in a code generator."""

    name: str

    _obj: Dict[str, str] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self._obj[key]

    def __iter__(self):
        return iter(self._obj)

    def __len__(self):
        return len(self._obj)

    def declare_c_variable(
        self,
        name: str,
        *,
        mode: ParamMode = ParamMode.OUT,
        name_token: str = "%C%",
        type_token: str = "%T%",
    ) -> str:
        """Returns a string that declares a new variable in C using this type.

        Parameters:
            name: the name of the C variable to declare

        Returns:
            a C variable declaration, without indentation or trailing newline
        """
        mode_str = str(mode.value).upper()
        c_decl = self._obj.get("CDECL")
        if isinstance(c_decl, dict):
            c_decl = c_decl.get(mode_str)

        c_type = self._obj.get("CTYPE")
        if isinstance(c_type, dict):
            c_type = c_type.get(mode_str)

        if c_decl is None:
            c_decl = f"{type_token} {name_token};"

        if c_type is None and type_token in c_decl:
            c_decl = ""

        return c_decl.replace(type_token, c_type or "").replace(name_token, name)

    def get_input_conversion_template_for(
        self, mode: ParamMode, *, default: str = ""
    ) -> str:
        """Returns a template string that specifies how parameters of this type
        should be converted when it is used as an input parameter.
        """
        if "INCONV" in self:
            inconv = self["INCONV"]
            if isinstance(inconv, str):
                return inconv if mode.is_input else default
            elif isinstance(inconv, dict):
                return inconv.get(mode.value.upper(), default)
            else:
                raise TypeError(
                    f"INCONV should be a string or a dict for type {self.name}"
                )
        else:
            return default

    def get_output_conversion_template_for(
        self, mode: ParamMode, *, default: str = ""
    ) -> str:
        """Returns a template string that specifies how parameters of this type
        should be converted when it is used as an output parameter.
        """
        if "OUTCONV" in self:
            outconv = self["OUTCONV"]
            if isinstance(outconv, str):
                return outconv if mode.is_output else default
            elif isinstance(outconv, dict):
                return outconv.get(mode.value.upper(), default)
            else:
                raise TypeError(
                    f"OUTCONV should be a string or a dict for type {self.name}"
                )
        else:
            return default

    def translate_default_value(self, value: Any) -> str:
        """Translates the default value of a parameter having this type to
        a string in the format that should be used in the output file.
        """
        mapping = self._obj.get("DEFAULT")
        if mapping is not None and value in mapping:
            return mapping[value]
        else:
            return str(value)

    def update_from(self, obj: Dict[str, str]) -> None:
        """Updates the type descriptor from an object typically parsed from
        a specification file.

        The rules are as follows:

          - Any key in `obj` is merged with the existing key-value store.
        """
        always_merger.merge(self._obj, obj)
