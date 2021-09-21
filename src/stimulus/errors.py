from typing import Optional

__all__ = ("StimulusError",)


class StimulusError(RuntimeError):
    """Base class for all errors specific to the `stimulus` package."""

    msg: str

    def __init__(self, message: str):
        super().__init__(message)
        self.msg = message

    def __str__(self):
        return str(self.msg)


class ParseError(StimulusError):
    """Base class for errors thrown while parsing input files."""

    lineno: Optional[int]

    def __init__(self, message: str, lineno: Optional[int] = None):
        super().__init__(
            f"{message} in line {lineno}" if lineno is not None else message
        )
        self.lineno = lineno
