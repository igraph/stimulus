__all__ = ("camelcase",)


def camelcase(s: str) -> str:
    """Returns a camelCase version of the given string (as used in Java
    libraries.
    """
    parts = s.split("_")
    result = [parts.pop(0)]
    for part in parts:
        result.append(part.capitalize())
    return "".join(result)
