"""Parser for the legacy `.def` file format that we used before migrating to
YAML.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, IO, List, Optional, Union

from ..errors import ParseError
from .lexer import tokenize, TokenType

__all__ = ("Parser",)


@dataclass
class StackFrame:
    """A single stack frame in the parser stack."""

    name: Optional[str] = None
    value: Optional[Union[str, Dict[str, Any]]] = None


class Parser:
    """Simple parser class for parsing the `.def` files that Stimulus uses for
    function and type descriptors.
    """

    def parse(self, stream: IO[str]) -> Dict[str, Any]:
        value: Dict[str, Any] = OrderedDict()
        stack: List[StackFrame] = [StackFrame(value=value), StackFrame()]

        for token in tokenize(stream):
            if token.type is TokenType.INDENT:
                stack.append(StackFrame())

            elif token.type is TokenType.DEDENT:
                frame = stack.pop()
                if frame.name is None:
                    stack[-1].value = frame.value
                else:
                    top_value = stack[-1].value
                    assert isinstance(top_value, dict)
                    top_value[frame.name] = frame.value

            elif token.type is TokenType.KEY:
                frame = stack.pop()
                if frame.name is not None:
                    top_value = stack[-1].value
                    assert isinstance(top_value, dict)
                    top_value[frame.name] = frame.value

                stack.append(StackFrame(name=token.value, value={}))

            elif token.type is TokenType.TEXT:
                stack[-1].value = token.value

            else:
                raise ParseError(f"Invalid token type {token.type}")

        return value


def test():
    from argparse import ArgumentParser
    from re import MULTILINE, sub
    from yaml import safe_dump
    from yaml.representer import SafeRepresenter

    arg_parser = ArgumentParser()
    arg_parser.add_argument("file", help="name of the input file to parse")
    arg_parser.add_argument(
        "-o",
        "--output",
        help=(
            "optional output file to save the YAML representation of the "
            "parsed input to"
        ),
        type=str,
        default=None,
    )
    options = arg_parser.parse_args()

    parser = Parser()
    with open(options.file) as fp:
        parsed = parser.parse(fp)

    dump_kwds = {"default_flow_style": False, "indent": 4}

    def ordered_dict_representer(dumper, data):
        """YAML representer that presents ordered dicts as ordinary Python
        dicts.
        """
        return dumper.represent_dict(data.items())

    def str_representer(dumper, data):
        """YAML representer that encodes multi-line strings in block format."""
        if "\n" in data:
            data = sub(r" *\n", "\n", data, flags=MULTILINE)
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        else:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    SafeRepresenter.add_representer(str, str_representer)
    SafeRepresenter.add_representer(OrderedDict, ordered_dict_representer)

    result = safe_dump(parsed, None, **dump_kwds)
    result = sub(r"^([A-Za-z])", "\n\\1", result, flags=MULTILINE)

    if options.output:
        with open(options.output, "w") as fp:
            fp.write(result)

    else:
        print(result)


if __name__ == "__main__":
    test()
