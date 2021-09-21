from typing import Callable

import getopt
import logging
import os
import sys

from .generators.base import CodeGenerator
from .generators.java import JavaCCodeGenerator, JavaJavaCodeGenerator  # noqa
from .generators.r import RCCodeGenerator, RRCodeGenerator  # noqa
from .generators.shell import ShellCodeGenerator, ShellLnCodeGenerator  # noqa
from .version import __version__


def usage():
    print(f"Stimulus {__version__}")
    print(sys.argv[0], "-f <function-file> -t <type-file> -l language ")
    print(" " * len(sys.argv[0]), "-i <input-file> -o <output-file>")
    print(" " * len(sys.argv[0]), "-h --help -v")


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


def main():
    logging.basicConfig(
        format="%(levelname)-10s| %(message)s", level=logging.INFO, stream=sys.stderr
    )

    # Command line arguments
    try:
        optlist, args = getopt.getopt(sys.argv[1:], "t:f:l:i:o:h", ["help"])
    except getopt.GetoptError:
        usage()
        sys.exit(2)

    type_files = []
    function_files = []
    inputs = []
    languages = []
    outputs = []

    for o, a in optlist:
        if o in ("-h", "--help"):
            usage()
            sys.exit()
        elif o == "-o":
            outputs.append(a)
        elif o == "-t":
            type_files.append(a)
        elif o == "-f":
            function_files.append(a)
        elif o == "-l":
            languages.append(a)
        elif o == "-i":
            inputs.append(a)

    # Parameter checks
    # Note: the lists might be empty, but languages and outputs must
    # have the same length.
    if len(languages) != len(outputs):
        print("Error: number of languages and output files must match")
        sys.exit(4)
    for language in languages:
        if not has_code_generator_class_for_language(language):
            print("Error: unknown language:", language)
            sys.exit(6)
    for f in type_files:
        if not os.access(f, os.R_OK):
            print("Error: cannot open type file:", f)
            sys.exit(5)
    for path in function_files:
        if not os.access(f, os.R_OK):
            print("Error: cannot open function file:", f)
            sys.exit(5)
    for f in inputs:
        if not os.access(f, os.R_OK):
            print("Error: cannot open input file:", f)
            sys.exit(5)
    # TODO: output files are not checked now

    # Construct a log that the generators can write their messages to
    log = logging.getLogger()

    # OK, do the trick:
    for language, output in zip(languages, outputs):
        factory = get_code_generator_class_for_language(language)

        generator = factory()
        generator.use_logger(log)
        for path in function_files:
            generator.load_function_rules_from_file(path)
        for path in type_files:
            generator.load_type_rules_from_file(path)

        if output == "-":
            generator.generate(inputs, sys.stdout)
        else:
            with open(output, "w"):
                generator.generate(inputs, output)


if __name__ == "__main__":
    main()
