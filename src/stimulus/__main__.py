import logging
import os
import sys

from argparse import ArgumentParser
from typing import Callable

from .generators.base import CodeGenerator
from .generators.java import JavaCCodeGenerator, JavaJavaCodeGenerator  # noqa
from .generators.r import RCCodeGenerator, RRCodeGenerator  # noqa
from .generators.shell import ShellCodeGenerator  # noqa
from .version import __version__


def get_code_generator_class_for_language(
    lang: str,
) -> Callable[[], CodeGenerator]:
    """Returns the class or factory function that is responsible for generating
    code in the given language.
    """
    return globals()[f"{lang}CodeGenerator"]


def has_code_generator_class_for_language(lang: str) -> bool:
    """Returns whether there is a class or factory function that is responsible
    for generating code in the given language.
    """
    try:
        get_code_generator_class_for_language(lang)
        return True
    except KeyError:
        return False


def create_argument_parser() -> ArgumentParser:
    parser = ArgumentParser()

    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    parser.add_argument(
        "-t",
        "--types",
        metavar="FILE",
        help="use the given type definition FILE",
        nargs="*",
    )

    parser.add_argument(
        "-f",
        "--functions",
        action="append",
        metavar="FILE",
        help="use the given function definition FILE",
    )

    parser.add_argument(
        "-l",
        "--language",
        action="append",
        metavar="LANGUAGE",
        help="generate code in the given LANGUAGE",
    )

    parser.add_argument(
        "-i",
        "--input",
        action="append",
        metavar="FILE",
        help="read input from the given FILE",
    )

    parser.add_argument(
        "-o",
        "--output",
        action="append",
        metavar="FILE",
        help="write output to the given FILE. Use '-' for standard output.",
    )

    return parser


def main():
    logging.basicConfig(
        format="%(levelname)-10s| %(message)s", level=logging.INFO, stream=sys.stderr
    )

    parser = create_argument_parser()
    options = parser.parse_args()

    type_files = options.types
    function_files = options.functions
    inputs = options.input
    languages = options.language
    outputs = options.output

    # Parameter checks
    # Note: the lists might be empty, but languages and outputs must
    # have the same length.
    if len(languages) != len(outputs):
        parser.error("Number of languages and output files must match")

    for language in languages:
        if not has_code_generator_class_for_language(language):
            parser.error(f"Unknown language: {language}")

    for path in type_files:
        if not os.access(path, os.R_OK):
            parser.error(f"Cannot open type file: {path}")

    for path in function_files:
        if not os.access(path, os.R_OK):
            parser.error(f"Error: cannot open function file: {path}")

    for path in inputs:
        if not os.access(path, os.R_OK):
            parser.error(f"Error: cannot open input file: {path}")

    # Construct a log that the generators can write their messages to
    log = logging.getLogger()

    # OK, do the trick:
    for language, output in zip(languages, outputs):
        factory = get_code_generator_class_for_language(language)

        generator = factory()
        generator.use_logger(log)
        for path in function_files:
            generator.load_function_descriptors_from_file(path)
        for path in type_files:
            generator.load_type_descriptors_from_file(path)

        if output == "-":
            generator.generate(inputs, sys.stdout)
        else:
            with open(output, "w") as fp:
                generator.generate(inputs, fp)


if __name__ == "__main__":
    main()
