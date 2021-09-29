from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, IO, List, Optional, Union

from .errors import ParseError
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
    from pprint import pprint

    arg_parser = ArgumentParser()
    arg_parser.add_argument("file", help="name of the input file to parse")
    options = arg_parser.parse_args()

    parser = Parser()
    with open(options.file) as fp:
        pprint(parser.parse(fp))


if __name__ == "__main__":
    test()
