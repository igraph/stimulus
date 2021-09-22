from __future__ import annotations

import re

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, IO, Iterator, List

from .errors import ParseError

__all__ = ("Token", "TokenType", "tokenize")


class TokenType(Enum):
    """Types of tokens that the lexer can parse from an input file."""

    DEDENT = "dedent"
    INDENT = "indent"
    KEY = "key"
    TEXT = "text"


@dataclass(frozen=True)
class Token:
    """Simple data class representing a single token that the lexer parsed
    from an input file.
    """

    #: The type of the token
    type: TokenType

    #: The value of the token
    value: str = ""

    #: Singleton "dedent" token
    DEDENT: ClassVar[Token]

    #: Singleton "indent" token
    INDENT: ClassVar[Token]

    @classmethod
    def key(cls, value: str):
        """Creates a KEY token with the given value."""
        return cls(type=TokenType.KEY, value=value)

    @classmethod
    def text(cls, value: str):
        """Creates a TEXT token with the given value."""
        return cls(type=TokenType.TEXT, value=value)


Token.DEDENT = Token(type=TokenType.DEDENT)
Token.INDENT = Token(type=TokenType.INDENT)


def tokenize(stream: IO[str]) -> Iterator[Token]:
    """Tokenizes a Stimulus definition file from the given input stream.

    Yields:
        the tokens parsed from the definition file

    Raises:
        ParseError: when an error occurs while parsing the definition file
    """
    indent_stack: List[int] = [0]
    lineno: int = 0

    # Read a line, skip empty lines and comments
    while True:
        line = stream.readline()
        lineno += 1

        if line == "":
            # End of file reached, dedent completely
            while indent_stack:
                yield Token.DEDENT
                indent_stack.pop()
            return

        if re.match("^[ \t]*$", line):
            # Ignore empty lines
            continue

        if re.match("^[ \t]*#", line):
            # Ignore lines with comments
            continue

        # Strip newlines from end
        line = line.strip("\n")

        # Determine current indentation level
        match = re.match(r"^[ \t]*", line)
        assert match is not None
        indent_level = match.span()[1]

        # Strip leading and trailing whitespace
        line = line.strip()

        if indent_level > indent_stack[-1]:
            indent_stack.append(indent_level)
            yield Token.INDENT
        else:
            while indent_level < indent_stack[-1]:
                indent_stack.pop()
                yield Token.DEDENT

            if indent_level != indent_stack[-1]:
                raise ParseError("Bad indentation", lineno)

        # Ok, we're done with the whitespace, now let's see
        # whether this line is continued in the next one
        while line.endswith("\\"):
            line = line[:-1] + "\n  " + stream.readline().strip()
            lineno = lineno + 1

        # We have the line now, check whether there is a ':' in it
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if sep:
            if not key:
                raise ParseError("Missing keyword", lineno)

            keys = [k.strip() for k in key.split(",")]
            if not value:
                for key in keys:
                    yield Token.key(key)
            else:
                for key in keys:
                    yield Token.key(key)
                    yield Token.INDENT
                    yield Token.text(value)
                    yield Token.DEDENT
        else:
            # No ':', simply yield the line as is
            yield Token.text(key)


def test():
    from argparse import ArgumentParser
    from pprint import pprint

    parser = ArgumentParser()
    parser.add_argument("file", help="name of the input file to parse")
    options = parser.parse_args()

    with open(options.file) as fp:
        for token in tokenize(fp):
            pprint(token)


if __name__ == "__main__":
    test()
