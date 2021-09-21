from collections import OrderedDict
from typing import Any, Callable, Dict

import getopt
import os
import re
import sys

from .errors import StimulusError
from .generators.base import CodeGenerator, CodeGeneratorBase, ParamMode, ParamSpec
from .version import __version__


def usage():
    print(f"Stimulus {__version__}")
    print(sys.argv[0], "-f <function-file> -t <type-file> -l language ")
    print(" " * len(sys.argv[0]), "-i <input-file> -o <output-file>")
    print(" " * len(sys.argv[0]), "-h --help -v")


################################################################################
################################################################################


def get_code_generator_class_for_language(
    lang: str,
) -> Callable[[], CodeGenerator]:
    return globals()[f"{lang}CodeGenerator"]


def has_code_generator_class_for_language(lang: str) -> bool:
    try:
        get_code_generator_class_for_language(lang)
        return True
    except KeyError:
        return False


def main():
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

    # OK, do the trick:
    for language, output in zip(languages, outputs):
        factory = get_code_generator_class_for_language(language)
        generator = factory()
        for path in function_files:
            generator.load_function_rules_from_file(path)
        for path in type_files:
            generator.load_type_rules_from_file(path)

        if output == "-":
            generator.generate(inputs, sys.stdout)
        else:
            with open(output, "w"):
                generator.generate(inputs, output)


################################################################################
# GNU R, see http://www.r-project.org
# TODO: free memory when CTRL+C pressed, even on windows
################################################################################


class RNamespaceCodeGenerator(CodeGeneratorBase):
    def generate(self, inputs, output):
        """This is very simple, we include an 'export' line for every
        function which it not to be ignored by the RNamespace language.
        Function names are taken from NAME-R if present, otherwise
        underscores are converted to dots and the leading 'i' (from
        'igraph') is stripped to create the function name,
        ie. igraph_clusters is mapped to graph.clusters."""
        out = open(output, "w")
        self.append_inputs(inputs, out)
        for f in self.func.keys():
            if self.should_ignore_function(f):
                continue
            name = self.func[f].get("NAME-R", f[1:].replace("_", "."))
            out.write("export(" + name + ")\n")
        out.close()


class RRCodeGenerator(CodeGeneratorBase):
    def generate_function(self, function, out):

        # Ignore?
        if self.should_ignore_function(function):
            return

        name = self.func[function].get("NAME-R", function[1:].replace("_", "."))
        params = self.get_parameters_for_function(function)
        self.deps = self.get_dependencies_for_function(function)

        # Check types
        for p in params:
            tname = params[p].type
            if tname not in self.types:
                print("Error: Unknown type encountered:", tname)
                sys.exit(7)

        ## Roxygen to export the function
        internal = self.func[function].get("INTERNAL")
        if internal is None or internal == "False":
            out.write("#' @export\n")

        ## Header
        ## do_par handles the translation of a single argument in the
        ## header. Pretty simple, the only difficulty is that we
        ## might need to add default values. Default values are taken
        ## from a language specific dictionary, this is compiled from
        ## the type file(s).

        ## So we take all arguments with mode 'IN' or 'INOUT' and
        ## check whether they have a default value. If yes then we
        ## check if the default value is given in the type file. If
        ## yes then we use the value given there, otherwise the
        ## default value is ignored silently. (Not very nice.)

        out.write(name)
        out.write(" <- function(")

        def do_par(pname):
            tname = params[pname].type
            t = self.types[tname]
            default = ""
            header = pname.replace("_", ".")
            if "HEADER" in t:
                header = t["HEADER"]
            if header:
                header = header.replace("%I%", pname.replace("_", "."))
            else:
                header = ""
            if params[pname].default is not None:
                if "DEFAULT" in t and params[pname].default in t["DEFAULT"]:
                    default = "=" + t["DEFAULT"][params[pname].default]
                else:
                    default = "=" + str(params[pname].default)
            header = header + default
            if pname in list(self.deps.keys()):
                deps = self.deps[pname]
                for i, dep in enumerate(deps):
                    header = header.replace("%I" + str(i + 1) + "%", dep)
            if re.search("%I[0-9]*%", header):
                print(
                    "Error: Missing HEADER dependency for "
                    + tname
                    + " "
                    + pname
                    + " in function "
                    + name
                )
            return header

        head = [do_par(n) for n, p in params.items() if p.is_input]
        head = [h for h in head if h != ""]
        out.write(", ".join(head))
        out.write(") {\n")

        ## Argument checks, INCONV
        ## We take 'IN' and 'INOUT' mode arguments and if they have an
        ## INCONV field then we use that. This is typically for
        ## argument checks, like we check here that the argument
        ## supplied for a graph is indeed an igraph graph object. We
        ## also covert numeric vectors to 'double' here.

        ## The INCONV fields are simply concatenated by newline
        ## characters.
        out.write("  # Argument checks\n")

        def do_par(pname):
            tname = params[pname].type
            t = self.types[tname]
            mode = params[pname].mode_str
            if params[pname].is_input and "INCONV" in t:
                if mode in t["INCONV"]:
                    res = "  " + t["INCONV"][mode]
                else:
                    res = "  " + t["INCONV"]
            else:
                res = ""
            res = res.replace("%I%", pname.replace("_", "."))

            if pname in list(self.deps.keys()):
                deps = self.deps[pname]
                for i, dep in enumerate(deps):
                    res = res.replace("%I" + str(i + 1) + "%", dep)
            if re.search("%I[0-9]*%", res):
                print(
                    (
                        "Error: Missing IN dependency for "
                        + tname
                        + " "
                        + pname
                        + " in function "
                        + name
                    )
                )
            return res

        inconv = [do_par(n) for n in list(params.keys())]
        inconv = [i for i in inconv if i != ""]
        out.write("\n".join(inconv) + "\n\n")

        ## Function call
        ## This is a bit more difficult than INCONV. Here we supply
        ## each argument to the .Call function, if the argument has a
        ## 'CALL' field then it is used, otherwise we simply use its
        ## name.
        ## argument. Note that arguments with empty CALL fields are
        ## completely ignored, so giving an empty CALL field is
        ## different than not giving it at all.

        ## Function call
        def do_par(pname):
            t = self.types[params[pname].type]
            call = pname.replace("_", ".")
            if "CALL" in t:
                call = t["CALL"]
                if call:
                    call = call.replace("%I%", pname.replace("_", "."))
                else:
                    call = ""
            return call

        out.write("  on.exit( .Call(C_R_igraph_finalizer) )\n")
        out.write("  # Function call\n")
        out.write("  res <- .Call(C_R_" + function + ", ")
        call = [do_par(n) for n, p in params.items() if p.is_input]
        call = [c for c in call if c != ""]
        out.write(", ".join(call))
        out.write(")\n")

        ## Output conversions
        def do_opar(pname, realname=None, iprefix=""):
            if realname is None:
                realname = pname
            tname = params[pname].type
            t = self.types[tname]
            mode = params[pname].mode_str
            if "OUTCONV" in t and mode in t["OUTCONV"]:
                outconv = "  " + t["OUTCONV"][mode]
            else:
                outconv = ""
            outconv = outconv.replace("%I%", iprefix + realname)

            if pname in list(self.deps.keys()):
                deps = self.deps[pname]
                for i, dep in enumerate(deps):
                    outconv = outconv.replace("%I" + str(i + 1) + "%", dep)
            if re.search("%I[0-9]*%", outconv):
                print(outconv)
                print(self.deps)
                print(
                    (
                        "Error: Missing OUT dependency for "
                        + tname
                        + " "
                        + pname
                        + " in function "
                        + name
                    )
                )
            return re.sub("%I[0-9]+%", "", outconv)

        retpars = [n for n, p in params.items() if p.is_output]

        if len(retpars) <= 1:
            outconv = [do_opar(n, "res") for n in list(params.keys())]
        else:
            outconv = [do_opar(n, iprefix="res$") for n in list(params.keys())]

        outconv = [o for o in outconv if o != ""]

        if len(retpars) == 0:
            # returning the return value of the function
            rt = self.types[self.func[function]["RETURN"]]
            if "OUTCONV" in rt:
                retconv = "  " + rt["OUTCONV"]["OUT"]
            else:
                retconv = ""
            retconv = retconv.replace("%I%", "res")
            # TODO: %I1% etc, is not handled here!
            ret = "\n".join(outconv) + "\n" + retconv + "\n"
        elif len(retpars) == 1:
            # returning a single output value
            ret = "\n".join(outconv) + "\n"
        else:
            # returning a list of output values
            None
            ret = "\n".join(outconv) + "\n"
        out.write(ret)

        ## Some graph attributes to add
        if "GATTR-R" in list(self.func[function].keys()):
            gattrs = self.func[function]["GATTR-R"].split(",")
            gattrs = [ga.split(" IS ", 1) for ga in gattrs]
            sstr = "  res <- set.graph.attribute(res, '{name}', '{val}')\n"
            for ga in gattrs:
                aname = ga[0].strip()
                aval = ga[1].strip().replace("'", "\\'")
                out.write(sstr.format(name=aname, val=aval))

        ## Add some parameters as graph attributes
        if "GATTR-PARAM-R" in list(self.func[function].keys()):
            pars = self.func[function]["GATTR-PARAM-R"].split(",")
            pars = [p.strip().replace("_", ".") for p in pars]
            sstr = "  res <- set.graph.attribute(res, '{par}', {par})\n"
            for p in pars:
                out.write(sstr.format(par=p))

        ## Set the class if requested
        if "CLASS-R" in list(self.func[function].keys()):
            myclass = self.func[function]["CLASS-R"]
            out.write('  class(res) <- "' + myclass + '"\n')

        ## See if there is a postprocessor
        if "PP-R" in list(self.func[function].keys()):
            pp = self.func[function]["PP-R"]
            out.write("  res <- " + pp + "(res)\n")

        out.write("  res\n}\n\n")


class RCCodeGenerator(CodeGeneratorBase):
    def generate_function(self, function, out):

        # Ignore?
        if self.should_ignore_function(function):
            return

        params = self.get_parameters_for_function(function)
        self.deps = self.get_dependencies_for_function(function)

        # Check types
        for p in params:
            tname = params[p].type
            if tname not in self.types:
                print("Error: Unknown type " + tname + " in " + function)
                return

        ## Compile the output
        ## This code generator is quite difficult, so we use different
        ## functions to generate the approprite chunks and then
        ## compile them together using a simple template.
        ## See the documentation of each chunk below.
        res = {}
        res["func"] = function
        res["header"] = self.chunk_header(function, params)
        res["decl"] = self.chunk_declaration(function, params)
        res["inconv"] = self.chunk_inconv(function, params)
        res["call"] = self.chunk_call(function, params)
        res["outconv"] = self.chunk_outconv(function, params)

        # Replace into the template
        text = (
            """
/*-------------------------------------------/
/ %(func)-42s /
/-------------------------------------------*/
%(header)s {
                                        /* Declarations */
%(decl)s
                                        /* Convert input */
%(inconv)s
                                        /* Call igraph */
%(call)s
                                        /* Convert output */
%(outconv)s

  UNPROTECT(1);
  return(result);
}\n"""
            % res
        )

        out.write(text)

    def chunk_header(self, function, params):
        """The header. All functions return with a 'SEXP', so this is
        easy. We just take the 'IN' and 'INOUT' arguments, all will
        have type SEXP, and concatenate them by commas. The function name
        is created by prefixing the original name with 'R_'."""

        def do_par(pname):
            t = self.types[params[pname].type]
            if "HEADER" in t:
                if t["HEADER"]:
                    return t["HEADER"].replace("%I%", pname)
                else:
                    return ""
            else:
                return pname

        inout = [do_par(n) for n, p in params.items() if p.is_input]
        inout = ["SEXP " + n for n in inout if n != ""]
        return "SEXP R_" + function + "(" + ", ".join(inout) + ")"

    def chunk_declaration(self, function, params):
        """There are a couple of things to declare. First a C type is
        needed for every argument, these will be supplied in the C
        igraph call. Then, all 'OUT' arguments need a SEXP variable as
        well, the result will be stored here. The return type
        of the C function also needs to be declared, that comes
        next. The result and names SEXP variables will contain the
        final result, these are last. ('names' is not always used, but
        it is easier to always declare it.)
        """

        def do_par(pname):
            cname = "c_" + pname
            t = self.types[params[pname].type]
            if "DECL" in t:
                decl = "  " + t["DECL"]
            elif "CTYPE" in t:
                ctype = t["CTYPE"]
                if type(ctype) == dict:
                    mode = params[pname].mode_str
                    decl = "  " + ctype[mode] + " " + cname + ";"
                else:
                    decl = "  " + ctype + " " + cname + ";"
            else:
                decl = ""
            return decl.replace("%C%", cname).replace("%I%", pname)

        inout = [do_par(n) for n in list(params.keys())]
        out = [
            "  SEXP " + n + ";" for n, p in params.items() if p.mode is ParamMode.OUT
        ]

        retpars = [n for n, p in params.items() if p.is_output]

        rt = self.types[self.func[function]["RETURN"]]
        if "DECL" in rt:
            retdecl = "  " + rt["DECL"]
        elif "CTYPE" in rt and len(retpars) == 0:
            ctype = rt["CTYPE"]
            if type(ctype) == dict:
                mode = params[pname].mode_str  # noqa
                retdecl = "  " + ctype[mode] + " " + "c_result;"
            else:
                retdecl = "  " + rt["CTYPE"] + " c_result;"
        else:
            retdecl = ""

        if len(retpars) <= 1:
            res = "\n".join(inout + out + [retdecl] + ["  SEXP result;"])
        else:
            res = "\n".join(inout + out + [retdecl] + ["  SEXP result, names;"])
        return res

    def chunk_inconv(self, function, params):
        """Input conversions. Not only for types with mode 'IN' and
        'INOUT', eg. for 'OUT' vector types we need to allocate the
        required memory here, do all the initializations, etc. Types
        without INCONV fields are ignored. The usual %C%, %I% is
        performed at the end.
        """

        def do_par(pname):
            cname = "c_" + pname
            t = self.types[params[pname].type]
            mode = params[pname].mode_str
            if "INCONV" in t and mode in t["INCONV"]:
                inconv = "  " + t["INCONV"][mode]
            else:
                inconv = ""

            if pname in list(self.deps.keys()):
                deps = self.deps[pname]
                for i, dep in enumerate(deps):
                    inconv = inconv.replace("%C" + str(i + 1) + "%", "c_" + dep)

            return inconv.replace("%C%", cname).replace("%I%", pname)

        inconv = [do_par(n) for n in list(params.keys())]
        inconv = [i for i in inconv if i != ""]

        return "\n".join(inconv)

    def chunk_call(self, function, params):
        """Every single argument is included, independently of their
        mode. If a type has a 'CALL' field then that is used after the
        usual %C% and %I% substitutions, otherwise the standard 'c_'
        prefixed C argument name is used.
        """

        def docall(t, n):
            if type(t) == dict:
                mode = params[n].mode_str
                if mode in t:
                    return t[mode]
                else:
                    return ""
            else:
                return t

        types = [self.types[params[n].type] for n in list(params.keys())]
        call = list(
            map(
                lambda t, n: docall(t.get("CALL", "c_" + n), n),
                types,
                list(params.keys()),
            )
        )
        call = list(
            map(
                lambda c, n: c.replace("%C%", "c_" + n).replace("%I%", n),
                call,
                list(params.keys()),
            )
        )
        retpars = [n for n, p in params.items() if p.is_output]
        call = [c for c in call if c != ""]
        res = "  " + function + "(" + ", ".join(call) + ");\n"
        if len(retpars) == 0:
            res = "  c_result=" + res
        return res

    def chunk_outconv(self, function, params):
        """The output conversions, this is quite difficult. A function
        may report its results in two ways: by returning it directly
        or by setting a variable to which a pointer was passed. igraph
        usually uses the latter and returns error codes, except for
        some simple functions like 'igraph_vcount()' which cannot
        fail.

        First we add the output conversion for all types. This is
        easy. Note that even 'IN' arguments may have output
        conversion, eg. this is the place to free memory allocated to
        them in the 'INCONV' part.

        Then we check how many 'OUT' or 'INOUT' arguments we
        have. There are three cases. If there is a single such
        argument then that is already converted and we need to return
        that. If there is no such argument then the output of the
        function was returned, so we perform the output conversion for
        the returned type and this will be the result. If there are
        more than one 'OUT' and 'INOUT' arguments then they are
        collected in a named list. The names come from the argument
        names.
        """

        def do_par(pname):
            cname = "c_" + pname
            t = self.types[params[pname].type]
            mode = params[pname].mode_str
            if "OUTCONV" in t and mode in t["OUTCONV"]:
                outconv = "  " + t["OUTCONV"][mode]
            else:
                outconv = ""

            if pname in list(self.deps.keys()):
                deps = self.deps[pname]
                for i, dep in enumerate(deps):
                    outconv = outconv.replace("%C" + str(i + 1) + "%", "c_" + dep)
            return outconv.replace("%C%", cname).replace("%I%", pname)

        outconv = [do_par(n) for n in list(params.keys())]
        outconv = [o for o in outconv if o != ""]

        retpars = [n for n, p in params.items() if p.is_output]
        if len(retpars) == 0:
            # return the return value of the function
            rt = self.types[self.func[function]["RETURN"]]
            if "OUTCONV" in rt:
                retconv = "  " + rt["OUTCONV"]["OUT"]
            else:
                retconv = ""
            retconv = retconv.replace("%C%", "c_result").replace("%I%", "result")
            ret = "\n".join(outconv) + "\n" + retconv
        elif len(retpars) == 1:
            # return the single output value
            retconv = "  result=" + retpars[0] + ";"
            ret = "\n".join(outconv) + "\n" + retconv
        else:
            # create a list of output values
            sets = list(
                map(
                    lambda c, n: "  SET_VECTOR_ELT(result, " + str(c) + ", " + n + ");",
                    list(range(len(retpars))),
                    retpars,
                )
            )
            names = list(
                map(
                    lambda c, n: "  SET_STRING_ELT(names, "
                    + str(c)
                    + ', CREATE_STRING_VECTOR("'
                    + n
                    + '"));',
                    list(range(len(retpars))),
                    retpars,
                )
            )
            ret = "\n".join(
                [
                    "  PROTECT(result=NEW_LIST(" + str(len(retpars)) + "));",
                    "  PROTECT(names=NEW_CHARACTER(" + str(len(retpars)) + "));",
                ]
                + outconv
                + sets
                + names
                + ["  SET_NAMES(result, names);"]
                + ["  UNPROTECT(" + str(len(sets) + 1) + ");"]
            )

        return ret


################################################################################
# Java interface, experimental version using JNI (Java Native Interface)
# TODO: - everything :) This is just a PoC implementation.
################################################################################


class JavaCodeGenerator(CodeGeneratorBase):
    """Class containing the common parts of JavaJavaCodeGenerator and
    JavaCCodeGenerator"""

    package = "net.sf.igraph"

    @staticmethod
    def camelcase(s: str) -> str:
        """Returns a camelCase version of the given string (as used in Java
        libraries"""
        parts = s.split("_")
        result = [parts.pop(0)]
        for part in parts:
            result.append(part.capitalize())
        return "".join(result)

    def get_function_metadata(self, f, type_param="JAVATYPE"):
        """Returns metadata for the given function based on the parameters.
        f is the name of the function. The result is a dict with the following
        keys:

        - java_modifiers: Java modifiers to be used in the .java file
        - return_type: return type of the function
        - name: name of the function
        - argument_types: list of argument types
        - self_name: name of the "self" argument
        - is_static: whether the function is static
        - is_constructor: whether the function is a constructor
        """
        params = self.get_parameters_for_function(f)
        is_constructor = False

        # We will collect data related to the current function in a dict
        data = {}
        data["name"] = self.func[f].get("NAME-JAVA", JavaCodeGenerator.camelcase(f[7:]))
        data["java_modifiers"] = ["public"]

        # Check parameter types to determine Java calling semantics
        types = {"IN": [], "OUT": [], "INOUT": []}
        for p in params:
            types[params[p].mode_str].append(params[p])

        if len(types["OUT"]) + len(types["INOUT"]) == 1:
            # If a single one is OUT or INOUT and all others are
            # INs, then this is our lucky day - the method fits the Java
            # semantics
            if len(types["OUT"]) > 0:
                return_type_name = types["OUT"][0].type
            else:
                return_type_name = types["INOUT"][0].type
        elif len(types["OUT"]) + len(types["INOUT"]) == 0 and "RETURN" in self.func[f]:
            # There are only input parameters and the return type is specified,
            # this also fits the Java semantics
            return_type_name = self.func[f]["RETURN"]
        else:
            raise StimulusError(
                "{}: calling convention unsupported yet".format(data["name"])
            )

        # Loop through the input parameters
        method_arguments = []
        found_self = False
        for p in params:
            if params[p].mode_str != "IN":
                continue
            type_name = params[p].type
            if not found_self and type_name == "GRAPH":
                # this will be the 'self' argument
                found_self = True
                data["self_name"] = p
                continue
            tdesc = self.types.get(type_name, {})
            if type_param not in tdesc:
                raise StimulusError(
                    "{}: unknown input type {} (needs {}), skipping".format(
                        data["name"], type_name, type_param
                    )
                )
            method_arguments.append(" ".join([tdesc[type_param], p]))
        data["argument_types"] = method_arguments

        if not found_self:
            # Loop through INOUT arguments if we found no "self" yet
            for p in params:
                if params[p].mode is ParamMode.OUT and params[p].type == "GRAPH":
                    found_self = True
                    data["self_name"] = p
                    break

        tdesc = self.types.get(return_type_name, {})
        if type_param not in tdesc:
            raise StimulusError(
                "{}: unknown return type {}, skipping".format(
                    data["name"], return_type_name
                )
            )
        data["return_type"] = tdesc[type_param]

        if not found_self:
            data["java_modifiers"].append("static")
            data["name"] = data["name"][0].upper() + data["name"][1:]

        data["java_modifiers"] = " ".join(data["java_modifiers"])
        data["is_static"] = not found_self
        data["is_constructor"] = is_constructor

        return data


class JavaJavaCodeGenerator(JavaCodeGenerator):
    def generate(self, inputs, output):
        out = open(output, "w")

        if len(inputs) > 1:
            raise StimulusError("Java code generator supports only a single input")

        input = open(inputs[0], "rU")
        for line in input:
            if "%STIMULUS%" not in line:
                out.write(line)
                continue

            for f in list(self.func.keys()):
                if self.should_ignore_function(f):
                    continue
                try:
                    func_metadata = self.get_function_metadata(f)
                    func_metadata["arguments"] = ", ".join(
                        func_metadata["argument_types"]
                    )
                    out.write(
                        "    %(java_modifiers)s native %(return_type)s %(name)s(%(arguments)s);\n"
                        % func_metadata
                    )
                except StimulusError as e:
                    out.write("    // %s\n" % str(e))

        out.close()


class JavaCCodeGenerator(JavaCodeGenerator):
    def generate_function(self, function, out):
        # Ignore?
        if self.should_ignore_function(function):
            return

        try:
            self.metadata = self.get_function_metadata(function, "CTYPE")
        except StimulusError as e:
            out.write("/* %s */\n" % str(e))
            return

        params = self.get_parameters_for_function(function)
        self.deps = self.get_dependencies_for_function(function)

        # Check types
        for p in params:
            tname = params[p].type
            if tname not in self.types:
                print("Error: Unknown type " + tname + " in " + function)
                return

        ## Compile the output
        ## This code generator is quite difficult, so we use different
        ## functions to generate the approprite chunks and then
        ## compile them together using a simple template.
        ## See the documentation of each chunk below.
        try:
            res = {}
            res["func"] = function
            res["header"] = self.chunk_header(function, params)
            res["decl"] = self.chunk_declaration(function, params)
            res["before"] = self.chunk_before(function, params)
            res["inconv"] = self.chunk_inconv(function, params)
            res["call"] = self.chunk_call(function, params)
            res["outconv"] = self.chunk_outconv(function, params)
            res["after"] = self.chunk_after(function, params)
        except StimulusError as e:
            out.write("/* %s */\n" % str(e))
            return

        # Replace into the template
        text = (
            """
/*-------------------------------------------/
/ %(func)-42s /
/-------------------------------------------*/
%(header)s {
                                        /* Declarations */
%(decl)s

%(before)s
                                        /* Convert input */
%(inconv)s
                                        /* Call igraph */
%(call)s
                                        /* Convert output */
%(outconv)s

%(after)s

  return result;
}\n"""
            % res
        )

        out.write(text)

    def chunk_header(self, function, params):
        """The header.

        The name of the function is the igraph function name minus the
        igraph_ prefix, camelcased and prefixed with the underscored
        Java classname: net_sf_igraph_Graph_. The arguments
        are mapped from the JAVATYPE key of the type dict. Static
        methods also need a 'jclass cls' argument, ordinary methods
        need 'jobject jobj'. Besides that, the Java environment pointer
        is also passed.
        """
        data = self.get_function_metadata(function, "JAVATYPE")

        data["funcname"] = "Java_%s_Graph_%s" % (
            self.package.replace(".", "_"),
            data["name"],
        )

        if data["is_static"]:
            data["argument_types"].insert(0, "jclass cls")
        else:
            data["argument_types"].insert(0, "jobject " + data["self_name"])
        data["argument_types"].insert(0, "JNIEnv *env")

        data["types"] = ", ".join(data["argument_types"])

        res = "JNIEXPORT %(return_type)s JNICALL %(funcname)s(%(types)s)" % data
        return res

    def chunk_declaration(self, function, params):
        """The declaration part of the function body

        There are a couple of things to declare. First a C type is
        needed for every argument, these will be supplied in the C
        igraph call. Then, all 'OUT' arguments need an appropriate variable as
        well, the result will be stored here. The return type
        of the C function also needs to be declared, that comes
        next. The result variable will contain the final result. Finally,
        if the method is not static but we are returning a new Graph object
        (e.g. in the case of igraph_linegraph), we need a jclass variable
        to store the Java class object."""

        def do_cpar(pname):
            cname = "c_" + pname
            t = self.types[params[pname].type]
            if "CDECL" in t:
                decl = "  " + t["CDECL"]
            elif "CTYPE" in t:
                decl = "  " + t["CTYPE"] + " " + cname + ";"
            else:
                decl = ""
            return decl.replace("%C%", cname).replace("%I%", pname)

        def do_jpar(pname):
            jname = "j_" + pname
            t = self.types[params[pname].type]
            if "JAVADECL" in t:
                decl = "  " + t["JAVADECL"]
            elif "JAVATYPE" in t:
                decl = "  " + t["JAVATYPE"] + " " + jname + ";"
            else:
                decl = ""
            return decl.replace("%J%", jname).replace("%I%", pname)

        inout = [do_cpar(n) for n in list(params.keys())]
        out = [do_jpar(n) for n, p in params.items() if p.mode is ParamMode.OUT]

        rt = self.types[self.func[function]["RETURN"]]
        if "CDECL" in rt:
            retdecl = "  " + rt["CDECL"]
        elif "CTYPE" in rt:
            retdecl = "  " + rt["CTYPE"] + " c__result;"
        else:
            retdecl = ""

        rnames = [n for n, p in params.items() if p.is_output]
        jretdecl = ""
        if len(rnames) > 0:
            n = rnames[0]
            rtname = params[n].type
        else:
            rtname = self.func[function]["RETURN"]
        rt = self.types[rtname]
        if "JAVADECL" in rt:
            jretdecl = "  " + rt["JAVADECL"]
        elif "JAVATYPE" in rt:
            jretdecl = "  " + rt["JAVATYPE"] + " result;"

        decls = inout + out + [retdecl, jretdecl]
        if not self.metadata["is_static"] and rtname == "GRAPH":
            self.metadata["need_class_decl"] = True
            decls.append(
                "  jclass cls = (*env)->GetObjectClass(env, %s);"
                % self.metadata["self_name"]
            )
        else:
            self.metadata["need_class_decl"] = False
        return "\n".join([i for i in decls if i != ""])

    def chunk_before(self, function, params):
        """We simply call Java_igraph_before"""
        return "  Java_igraph_before();"

    def chunk_inconv(self, function, params):
        """Input conversions. Not only for types with mode 'IN' and
        'INOUT', eg. for 'OUT' vector types we need to allocate the
        required memory here, do all the initializations, etc. Types
        without INCONV fields are ignored. The usual %C%, %I% is
        performed at the end.
        """

        def do_par(pname):
            cname = "c_" + pname
            t = self.types[params[pname].type]
            mode = params[pname].mode_str
            if "INCONV" in t and mode in t["INCONV"]:
                inconv = "  " + t["INCONV"][mode]
            else:
                inconv = ""

            if pname in list(self.deps.keys()):
                deps = self.deps[pname]
                for i, dep in enumerate(deps):
                    inconv = inconv.replace("%C" + str(i + 1) + "%", "c_" + dep)

            return inconv.replace("%C%", cname).replace("%I%", pname)

        inconv = [do_par(n) for n in list(params.keys())]
        inconv = [i for i in inconv if i != ""]

        return "\n".join(inconv)

    def chunk_call(self, function, params):
        """Every single argument is included, independently of their
        mode. If a type has a 'CALL' field then that is used after the
        usual %C% and %I% substitutions, otherwise the standard 'c_'
        prefixed C argument name is used.
        """
        types = [self.types[params[n].type] for n in list(params.keys())]
        call = list(
            map(lambda t, n: t.get("CALL", "c_" + n), types, list(params.keys()))
        )
        call = list(
            map(
                lambda c, n: c.replace("%C%", "c_" + n).replace("%I%", n),
                call,
                list(params.keys()),
            )
        )
        lines = [
            "  if ((*env)->ExceptionCheck(env)) {",
            "    c__result = IGRAPH_EINVAL;",
            "  } else {",
            "    c__result = " + function + "(" + ", ".join(call) + ");",
            "  }",
        ]
        return "\n".join(lines)

    def chunk_outconv(self, function, params):
        """The output conversions, this is quite difficult. A function
        may report its results in two ways: by returning it directly
        or by setting a variable to which a pointer was passed. igraph
        usually uses the latter and returns error codes, except for
        some simple functions like 'igraph_vcount()' which cannot
        fail.

        First we add the output conversion for all types. This is
        easy. Note that even 'IN' arguments may have output
        conversion, eg. this is the place to free memory allocated to
        them in the 'INCONV' part.

        Then we check how many 'OUT' or 'INOUT' arguments we
        have. There are three cases. If there is a single such
        argument then that is already converted and we need to return
        that. If there is no such argument then the output of the
        function was returned, so we perform the output conversion for
        the returned type and this will be the result. The case of
        more than one 'OUT' and 'INOUT' arguments is not yet supported by
        the Java interface.
        """

        def do_par(pname):
            cname = "c_" + pname
            jname = "j_" + pname
            t = self.types[params[pname].type]
            mode = params[pname].mode_str
            if "OUTCONV" in t and mode in t["OUTCONV"]:
                outconv = "  " + t["OUTCONV"][mode]
            else:
                outconv = ""
            return outconv.replace("%C%", cname).replace("%I%", jname)

        outconv = [do_par(n) for n in list(params.keys())]
        outconv = [o for o in outconv if o != ""]

        retpars = [(n, p) for n, p in params.items() if p.is_output]
        if len(retpars) == 0:
            # return the return value of the function
            rt = self.types[self.func[function]["RETURN"]]
            if "OUTCONV" in rt:
                retconv = "  " + rt["OUTCONV"]["OUT"]
            else:
                retconv = ""
            retconv = retconv.replace("%C%", "c__result").replace("%I%", "result")
            if len(retconv) > 0:
                outconv.append(retconv)
            ret = "\n".join(outconv)
        elif len(retpars) == 1:
            # return the single output value
            if retpars[0][1].mode is ParamMode.OUT:
                # OUT parameter
                retconv = "  result = j_" + retpars[0][0] + ";"
            else:
                # INOUT parameter
                retconv = "  result = " + retpars[0][0] + ";"
            outconv.append(retconv)

            outconv.insert(0, "if (c__result == 0) {")
            outconv.extend(["} else {", "  result = 0;", "}"])
            outconv = ["  %s" % line for line in outconv]
            ret = "\n".join(outconv)
        else:
            raise StimulusError(
                "{}: the case of multiple outputs not supported yet".format(function)
            )

        return ret

    def chunk_after(self, function, params):
        """We simply call Java_igraph_after"""
        return "  Java_igraph_after();"


################################################################################
# Shell interface, igraph functions directly from the command line
# TODO: - read/write default input/output from/to stdin/stdout
#       - short options
#       - prefixed output (?)
#       - default values depending on other parameters
#       - other input/output graph formats, to be controlled by
#         environment variables (?): IGRAPH_INGRAPH, IGRAPH_OUTGRAPH
################################################################################


class ShellLnCodeGenerator(CodeGeneratorBase):
    def generate(self, inputs, output):
        out = open(output, "w")
        self.append_inputs(inputs, out)
        for f in list(self.func.keys()):
            if self.should_ignore_function(f):
                continue
            out.write(f + "\n")
        out.close()


class ShellCodeGenerator(CodeGeneratorBase):
    def generate(self, inputs, output):
        out = open(output, "w")
        self.append_inputs(inputs, out)
        out.write("\n/* Function prototypes first */\n\n")

        for f in list(self.func.keys()):
            if self.should_ignore_function(f):
                continue
            if "FLAGS" in self.func[f]:
                flags = self.func[f]["FLAGS"]
                flags = flags.split(",")
                flags = [flag.strip() for flag in flags]
            else:
                self.func[f]["FLAGS"] = []
            self.generate_prototype(f, out)

        out.write("\n/* The main function */\n\n")
        out.write("int main(int argc, char **argv) {\n\n")
        out.write("  const char *base=basename(argv[0]);\n\n  ")
        for f in list(self.func.keys()):
            if self.should_ignore_function(f):
                continue
            out.write(
                'if (!strcasecmp(base, "'
                + f
                + '")) {\n    return shell_'
                + f
                + "(argc, argv);\n  } else "
            )
        out.write('{\n    printf("Unknown function, exiting\\n");\n')
        out.write("  }\n\n  shell_igraph_usage(argc, argv);\n  return 0;\n\n}\n")

        out.write("\n/* The functions themselves at last */\n")
        for f in list(self.func.keys()):
            if self.should_ignore_function(f):
                continue
            self.generate_function(f, out)

        out.close()

    def generate_prototype(self, function, out):
        out.write("int shell_" + function + "(int argc, char **argv);\n")

    def generate_function(self, function, out):
        params = self.get_parameters_for_function(function)

        # Check types, also enumerate them
        args = OrderedDict()
        for p in params:
            tname = params[p].type
            if tname not in self.types:
                print("W: Unknown type encountered:", tname)
                return

            t = self.types[tname]
            mode = params[p].mode
            if "INCONV" in t or "OUTCONV" in t:
                args[p] = params[p].as_dict()
                args[p]["shell_no"] = len(args) - 1
                if mode is ParamMode.INOUT:
                    args[p]["mode"] = "IN"
                    args[p + "-out"] = params[p].as_dict()
                    args[p + "-out"]["mode"] = "OUT"
                    args[p + "-out"]["shell_no"] = len(args) - 1
                    if "INCONV" not in t or "IN" not in t["INCONV"]:
                        print("Warning: no INCONV for type", tname, ", mode IN")
                    if "OUTCONV" not in t or "OUT" not in t["OUTCONV"]:
                        print("Warning: no OUTCONV for type", tname, ", mode OUT")
            if mode is ParamMode.IN and ("INCONV" not in t or mode not in t["INCONV"]):
                print("Warning: no INCONV for type", tname, ", mode", mode)
            if mode is ParamMode.OUT and (
                "OUTCONV" not in t or mode not in t["OUTCONV"]
            ):
                print("Warning: no OUTCONV for type", tname, ", mode", mode)

        res: Dict[str, Any] = {"nargs": len(args)}
        res["func"] = function
        res["args"] = self.chunk_args(function, args)
        res["decl"] = self.chunk_decl(function, params)
        res["inconv"] = self.chunk_inconv(function, args)
        res["call"] = self.chunk_call(function, params)
        res["outconv"] = self.chunk_outconv(function, args)
        res["default"] = self.chunk_default(function, args)
        res["usage"] = self.chunk_usage(function, args)
        text = (
            """\
/*-------------------------------------------/
/ %(func)-42s /
/-------------------------------------------*/
void shell_%(func)s_usage(char **argv) {
%(usage)s
  exit(1);
}

int shell_%(func)s(int argc, char **argv) {

%(decl)s

  int shell_seen[%(nargs)s];
  int shell_index=-1;
  struct option shell_options[]= { %(args)s
                                   { "help",no_argument,0,%(nargs)s },
                                   { 0,0,0,0 }
                                 };

  /* 0 - not seen, 1 - seen as argument, 2 - seen as default */
  memset(shell_seen, 0, %(nargs)s*sizeof(int));
%(default)s

  /* Parse arguments and read input */
  while (getopt_long(argc, argv, "", shell_options, &shell_index) != -1) {

    if (shell_index==-1) {
      exit(1);
    }

    if (shell_seen[shell_index]==1) {
      fprintf(stderr, "Error, `--%%s' argument given twice.\\n",
              shell_options[shell_index].name);
      exit(1);
    }
    shell_seen[shell_index]=1;
%(inconv)s
    shell_index=-1;
  }

  /* Check that we have all arguments */
  for (shell_index=0; shell_index<%(nargs)s; shell_index++) {
    if (!shell_seen[shell_index]) {
      fprintf(stderr, "Error, argument missing: `--%%s'.\\n",
              shell_options[shell_index].name);
      exit(1);
    }
  }

  /* Do the operation */
%(call)s

  /* Write the result */
%(outconv)s

  return 0;
}\n"""
            % res
        )
        out.write(text)

    def chunk_args(self, function, params):
        res = [
            ['"' + n + '"', "required_argument", "0", str(p["shell_no"])]
            for n, p in params.items()
        ]
        res = ["{ " + ",".join(e) + " }," for e in res]
        return "\n                                   ".join(res)

    def chunk_decl(self, function, params: Dict[str, ParamSpec]):
        def do_par(pname):
            t = self.types[params[pname].type]
            if "DECL" in t:
                decl = "  " + t["DECL"].replace("%C%", pname)
            elif "CTYPE" in t:
                decl = "  " + t["CTYPE"] + " " + pname
            else:
                decl = ""
            if params[pname].default is not None:
                if "DEFAULT" in t and params[pname].default in t["DEFAULT"]:
                    default = "=" + t["DEFAULT"][params[pname].default]
                else:
                    default = "=" + str(params[pname].default)
            else:
                default = ""
            if decl:
                return decl + default + ";"
            else:
                return ""

        decl = [do_par(n) for n in list(params.keys())]
        inout = [
            "  char* shell_arg_" + n + "=0;" for n, p in params.items() if p.is_output
        ]
        rt = self.types[self.func[function]["RETURN"]]
        if "DECL" in rt:
            retdecl = "  " + rt["DECL"]
        elif "CTYPE" in rt:
            retdecl = "  " + rt["CTYPE"] + " shell_result;"
        else:
            retdecl = ""

        if self.func[function]["RETURN"] != "ERROR":
            retchar = '  char *shell_arg_shell_result="-";'
        else:
            retchar = ""
        return "\n".join(decl + inout + [retdecl, retchar])

    def chunk_default(self, function, params):
        def do_par(pname):
            if "default" in params[pname]:
                res = "  shell_seen[" + str(params[pname]["shell_no"]) + "]=2;"
            else:
                res = ""
            return res

        res = [do_par(n) for n in list(params.keys())]
        res = [n for n in res if n != ""]
        return "\n".join(res)

    def chunk_inconv(self, function, params):
        def do_par(pname):
            t = self.types[params[pname].type]
            mode = params[pname].mode_str
            if "INCONV" in t and mode in t["INCONV"]:
                inconv = "" + t["INCONV"][mode]
            else:
                inconv = ""
            if pname.endswith("-out"):
                pname = pname[0:-4]
            return inconv.replace("%C%", pname)

        inconv = [
            "    case " + str(p["shell_no"]) + ": /* " + n + " */\n      " + do_par(n)
            for n, p in params.items()
        ]
        inconv = [n + "\n      break;" for n in inconv]
        inconv = ["".join(n) for n in inconv]
        text = (
            "\n    switch (shell_index) {\n"
            + "\n".join(inconv)
            + "\n    case "
            + str(len(inconv))
            + ":\n      shell_"
            + function
            + "_usage(argv);\n      break;"
            + "\n    default:\n      break;\n    }\n"
        )
        return text

    def chunk_call(self, function, params):
        types = [self.types[params[n].type] for n in list(params.keys())]
        call = list(map(lambda t, n: t.get("CALL", n), types, list(params.keys())))
        call = list(map(lambda c, n: c.replace("%C%", n), call, list(params.keys())))
        return "  shell_result=" + function + "(" + ", ".join(call) + ");"

    def chunk_outconv(self, function, params):
        def do_par(pname):
            t = self.types[params[pname].type]
            mode = params[pname].mode_str
            if "OUTCONV" in t and mode in t["OUTCONV"]:
                outconv = "  " + t["OUTCONV"][mode]
            else:
                outconv = ""
            if pname.endswith("-out"):
                pname = pname[0:-4]
            return outconv.replace("%C%", pname)

        outconv = [do_par(n) for n in list(params.keys())]
        rt = self.types[self.func[function]["RETURN"]]
        if "OUTCONV" in rt and "OUT" in rt["OUTCONV"]:
            rtout = "  " + rt["OUTCONV"]["OUT"]
        else:
            rtout = ""
        outconv.append(rtout.replace("%C%", "shell_result"))
        outconv = [o for o in outconv if o != ""]
        return "\n".join(outconv)

    def chunk_usage(self, function, params):
        res = ["--" + n + "=<" + n + ">" for n in list(params.keys())]
        return '  printf("%s ' + " ".join(res) + '\\n", basename(argv[0]));'


################################################################################


if __name__ == "__main__":
    main()
