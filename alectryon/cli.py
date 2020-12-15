# Copyright © 2019 Clément Pit-Claudel
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import argparse
import inspect
import os
import os.path
import shutil
import sys

# Pipelines
# =========

def read_plain(_, fpath, fname):
    if fname == "-":
        return sys.stdin.read()
    with open(fpath, encoding="utf-8") as f:
        return f.read()

def read_json(_, fpath, fname):
    from json import load
    if fname == "-":
        return load(sys.stdin)
    with open(fpath, encoding="utf-8") as f:
        return load(f)

def parse_plain(contents):
    return [contents]

def _catch_parsing_errors(fpath, k, *args):
    from .literate import ParsingError
    try:
        return k(*args)
    except ParsingError as e:
        raise ValueError("{}:{}".format(fpath, e))

def code_to_rst(code, fpath, point, marker, input_language):
    if input_language == "coq":
        from .literate import coq2rst_marked as converter
    else:
        assert False
    return _catch_parsing_errors(fpath, converter, code, point, marker)

def rst_to_code(rst, fpath, point, marker, backend):
    if backend in ("coq", "coq+rst"):
        from .literate import rst2coq_marked as converter
    else:
        assert False
    return _catch_parsing_errors(fpath, converter, rst, point, marker)

def annotate_chunks(chunks, input_language, sertop_args, lean3_args):
    if input_language == "coq":
        from .serapi import SerAPI as prover
        prover_args = sertop_args
    elif input_language == "lean3":
        from .lean3 import Lean3 as prover
        prover_args = lean3_args
    else:
        assert False
    return prover.annotate(chunks, prover_args)

def register_docutils(v, sertop_args):
    from .docutils import setup, AlectryonTransform
    AlectryonTransform.SERTOP_ARGS = sertop_args
    setup()
    return v

def _gen_docutils_html(source, fpath,
                       webpage_style, include_banner, include_vernums,
                       html_assets, traceback, Parser, Reader):
    from docutils.core import publish_string
    from .docutils import HtmlTranslator, HtmlWriter

    # The encoding/decoding dance below happens because setting output_encoding
    # to "unicode" causes reST to generate a bad <meta> tag, and setting
    # input_encoding to "unicode" breaks the ‘.. include’ directive.

    html_assets.extend(HtmlTranslator.JS + HtmlTranslator.CSS)

    settings_overrides = {
        'traceback': traceback,
        'embed_stylesheet': False,
        'stylesheet_path': None,
        'stylesheet_dirs': [],
        'alectryon_banner': include_banner,
        'alectryon_vernums': include_vernums,
        'webpage_style': webpage_style,
        'input_encoding': 'utf-8',
        'output_encoding': 'utf-8'
    }

    parser = Parser()
    return publish_string(
        source=source.encode("utf-8"),
        source_path=fpath, destination_path=None,
        reader=Reader(parser), reader_name=None,
        parser=parser, parser_name=None,
        writer=HtmlWriter(), writer_name=None,
        settings=None, settings_spec=None,
        settings_overrides=settings_overrides, config_section=None,
        enable_exit_status=True).decode("utf-8")

def gen_literate_html(code, fpath, webpage_style,
                      include_banner, include_vernums,
                      html_assets, traceback, input_language):
    if input_language == "coq":
        from .docutils import RSTCoqParser as Parser, RSTCoqStandaloneReader as Reader
    else:
        assert False
    return _gen_docutils_html(code, fpath, webpage_style,
                         include_banner, include_vernums,
                         html_assets, traceback,
                         Parser, Reader)

def gen_rst_html(rst, fpath, webpage_style,
                 include_banner, include_vernums,
                 html_assets, traceback):
    from docutils.parsers.rst import Parser
    from docutils.readers.standalone import Reader
    return _gen_docutils_html(rst, fpath, webpage_style,
                         include_banner, include_vernums,
                         html_assets, traceback,
                         Parser, Reader)

def _docutils_cmdline(description, Reader, Parser):
    import locale
    locale.setlocale(locale.LC_ALL, '')

    from docutils.core import publish_cmdline, default_description
    from .docutils import setup, HtmlWriter

    setup()

    parser = Parser()
    publish_cmdline(
        reader=Reader(parser), parser=parser,
        writer=HtmlWriter(),
        settings_overrides={'stylesheet_path': None},
        description=(description + default_description)
    )

def _lint_docutils(source, fpath, Parser, traceback):
    from io import StringIO
    from docutils.utils import new_document
    from docutils.frontend import OptionParser
    from docutils.utils import Reporter
    from .docutils import JsErrorPrinter

    parser = Parser()
    settings = OptionParser(components=(Parser,)).get_default_values()
    settings.traceback = traceback
    observer = JsErrorPrinter(StringIO(), settings)
    document = new_document(fpath, settings)

    document.reporter.report_level = 0 # Report all messages
    document.reporter.halt_level = Reporter.SEVERE_LEVEL + 1 # Do not exit early
    document.reporter.stream = False # Disable textual reporting
    document.reporter.attach_observer(observer)
    parser.parse(source, document)

    return observer.stream.getvalue()

def lint_embedded_rst(code, fpath, traceback, input_language):
    if input_language == "coq":
        from .docutils import RSTCoqParser as Parser
    else:
        assert False
    return _lint_docutils(code, fpath, Parser, traceback)

def lint_rst(rst, fpath, traceback):
    from docutils.parsers.rst import Parser
    return _lint_docutils(rst, fpath, Parser, traceback)

def _scrub_fname(fname):
    import re
    return re.sub("[^-a-zA-Z0-9]", "-", fname)

def apply_transforms(annotated):
    from .transforms import default_transform
    for chunk in annotated:
        yield default_transform(chunk)

def gen_html_snippets(annotated, include_vernums, fname, input_language):
    from .html import HtmlGenerator
    from .pygments import make_highlighter, highlight_html
    highlighter = make_highlighter(highlight_html, input_language)
    return HtmlGenerator(highlighter, _scrub_fname(fname)).gen(annotated)

def gen_latex_snippets(annotated, input_language):
    from .latex import LatexGenerator
    from .pygments import make_highlighter, highlight_latex
    highlighter = make_highlighter(highlight_latex, input_language)
    return LatexGenerator(highlighter).gen(annotated)

COQDOC_OPTIONS = ['--body-only', '--no-glob', '--no-index', '--no-externals',
                  '-s', '--html', '--stdout', '--utf8']

def _run_coqdoc(coq_snippets, coqdoc_bin=None):
    """Get the output of coqdoc on coq_code."""
    from shutil import rmtree
    from tempfile import mkstemp, mkdtemp
    from subprocess import check_output
    coqdoc_bin = coqdoc_bin or os.path.join(os.getenv("COQBIN", ""), "coqdoc")
    dpath = mkdtemp(prefix="alectryon_coqdoc_")
    fd, filename = mkstemp(prefix="alectryon_coqdoc_", suffix=".v", dir=dpath)
    try:
        for snippet in coq_snippets:
            os.write(fd, snippet.encode("utf-8"))
            os.write(fd, b"\n(* --- *)\n") # Separator to prevent fusing
        os.close(fd)
        coqdoc = [coqdoc_bin, *COQDOC_OPTIONS, "-d", dpath, filename]
        return check_output(coqdoc, cwd=dpath, timeout=10).decode("utf-8")
    finally:
        rmtree(dpath)

def _gen_coqdoc_html(coqdoc_fragments):
    from bs4 import BeautifulSoup
    coqdoc_output = _run_coqdoc(fr.contents for fr in coqdoc_fragments)
    soup = BeautifulSoup(coqdoc_output, "html.parser")
    docs = soup.find_all(class_='doc')
    if len(docs) != sum(1 for c in coqdoc_fragments if not c.special):
        from pprint import pprint
        print("Coqdoc mismatch:", file=sys.stderr)
        pprint(list(zip(coqdoc_comments, docs)))
        raise AssertionError()
    return docs

def _gen_html_snippets_with_coqdoc(annotated, fname, input_language):
    from dominate.util import raw
    from .html import HtmlGenerator
    from .pygments import make_highlighter, highlight_html
    from .transforms import isolate_coqdoc, default_transform, CoqdocFragment

    highlighter = make_highlighter(highlight_html, input_language)
    writer = HtmlGenerator(highlighter, _scrub_fname(fname))

    parts = [part for fragments in annotated
             for part in isolate_coqdoc(fragments)]
    coqdoc = [part for part in parts
              if isinstance(part, CoqdocFragment)]
    coqdoc_html = iter(_gen_coqdoc_html(coqdoc))

    for part in parts:
        if isinstance(part, CoqdocFragment):
            if not part.special:
                yield [raw(str(next(coqdoc_html, None)))]
        else:
            fragments = default_transform(part.fragments)
            yield writer.gen_fragments(fragments)

def gen_html_snippets_with_coqdoc(annotated, html_classes, fname, input_language):
    html_classes.append("coqdoc")
    # ‘return’ instead of ‘yield from’ to update html_classes eagerly
    return _gen_html_snippets_with_coqdoc(annotated, fname, input_language)

def copy_assets(state, html_assets, copy_fn, output_directory):
    from .html import copy_assets as cp
    if copy_fn:
        cp(output_directory, assets=html_assets, copy_fn=copy_fn)
    return state

def dump_html_standalone(snippets, fname, webpage_style,
                         include_banner, include_vernums,
                         html_assets, html_classes):
    from dominate import tags, document
    from dominate.util import raw
    from . import GENERATOR
    from .serapi import SerAPI
    from .pygments import HTML_FORMATTER
    from .html import ASSETS, ADDITIONAL_HEADS, gen_banner, wrap_classes

    doc = document(title=fname)
    doc.set_attribute("class", "alectryon-standalone")

    doc.head.add(tags.meta(charset="utf-8"))
    doc.head.add(tags.meta(name="generator", content=GENERATOR))

    for hd in ADDITIONAL_HEADS:
        doc.head.add(raw(hd))
    for css in ASSETS.ALECTRYON_CSS:
        doc.head.add(tags.link(rel="stylesheet", href=css))
    for link in (ASSETS.IBM_PLEX_CDN, ASSETS.FIRA_CODE_CDN):
        doc.head.add(raw(link))
    for js in ASSETS.ALECTRYON_JS:
        doc.head.add(tags.script(src=js))

    html_assets.extend(ASSETS.ALECTRYON_CSS)
    html_assets.extend(ASSETS.ALECTRYON_JS)

    pygments_css = HTML_FORMATTER.get_style_defs('.highlight')
    doc.head.add(tags.style(pygments_css, type="text/css"))

    cls = wrap_classes(webpage_style, *html_classes)
    root = doc.body.add(tags.article(cls=cls))
    if include_banner:
        root.add(raw(gen_banner(SerAPI.version_info(), include_vernums)))
    for snippet in snippets:
        root.add(snippet)

    return doc.render(pretty=False)

def prepare_json(obj):
    from .json import json_of_annotated
    return json_of_annotated(obj)

def dump_json(js):
    from json import dumps
    return dumps(js, indent=4)

def dump_html_snippets(snippets):
    s = ""
    for snippet in snippets:
        s += snippet.render(pretty=True)
        s += "<!-- alectryon-block-end -->\n"
    return s

def dump_latex_snippets(snippets):
    s = ""
    for snippet in snippets:
        s += str(snippet)
        s += "\n%% alectryon-block-end\n"
    return s

def strip_extension(fname):
    for ext in EXTENSIONS:
        if fname.endswith(ext):
            return fname[:-len(ext)]
    return fname

def write_output(ext, contents, fname, output, output_directory, replace_ext=True):
    if output == "-" or (output is None and fname == "-"):
        sys.stdout.write(contents)
    else:
        if not output:
            fname = strip_extension(fname) if replace_ext else fname
            output = os.path.join(output_directory, fname + ext)
        with open(output, mode="w", encoding="utf-8") as f:
            f.write(contents)

def write_file(ext, replace_ext=True):
    return lambda contents, fname, output, output_directory: \
        write_output(ext, contents, fname, output, output_directory,
                     replace_ext=replace_ext)

# No ‘apply_transforms’ in JSON pipelines: (we save the prover output without
# modifications).
PIPELINES = {
    'coq.json': {
        'json':
        (read_json, annotate_chunks, prepare_json, dump_json,
         write_file(".io.json")),
        'snippets-html':
        (read_json, annotate_chunks, apply_transforms, gen_html_snippets,
         dump_html_snippets, write_file(".snippets.html")),
        'snippets-latex':
        (read_json, annotate_chunks, apply_transforms, gen_latex_snippets,
         dump_latex_snippets, write_file(".snippets.tex"))
    },
    'lean3.json': {
        'json':
        (read_json, annotate_chunks, prepare_json, dump_json,
         write_file(".io.json")),
        'snippets-html':
        (read_json, annotate_chunks, apply_transforms, gen_html_snippets,
         dump_html_snippets, write_file(".snippets.html")),
        'snippets-latex':
        (read_json, annotate_chunks, apply_transforms, gen_latex_snippets,
         dump_latex_snippets, write_file(".snippets.tex"))
    },
    'coq': {
        'null':
        (read_plain, parse_plain, annotate_chunks),
        'webpage':
        (read_plain, parse_plain, annotate_chunks, apply_transforms,
         gen_html_snippets, dump_html_standalone, copy_assets,
         write_file(".html", replace_ext=False)),
        'snippets-html':
        (read_plain, parse_plain, annotate_chunks, apply_transforms,
         gen_html_snippets, dump_html_snippets, write_file(".snippets.html")),
        'snippets-latex':
        (read_plain, parse_plain, annotate_chunks, apply_transforms,
         gen_latex_snippets, dump_latex_snippets, write_file(".snippets.tex")),
        'lint':
        (read_plain, register_docutils, lint_embedded_rst,
         write_file(".lint.json")),
        'rst':
        (read_plain, code_to_rst, write_file(".rst", replace_ext=False)),
        'json':
        (read_plain, parse_plain, annotate_chunks, prepare_json, dump_json,
         write_file(".io.json"))
    },
    'lean3': {
        'null':
        (read_plain, parse_plain, annotate_chunks),
        'webpage':
        (read_plain, parse_plain, annotate_chunks, apply_transforms,
         gen_html_snippets, dump_html_standalone, copy_assets,
         write_file(".html", replace_ext=False)),
        'snippets-html':
        (read_plain, parse_plain, annotate_chunks, apply_transforms,
         gen_html_snippets, dump_html_snippets, write_file(".snippets.html")),
        'snippets-latex':
        (read_plain, parse_plain, annotate_chunks, apply_transforms,
         gen_latex_snippets, dump_latex_snippets, write_file(".snippets.tex")),
        'json':
        (read_plain, parse_plain, annotate_chunks, prepare_json, dump_json,
         write_file(".io.json"))
    },
    'coq+rst': {
        'webpage':
        (read_plain, register_docutils, gen_literate_html, copy_assets,
         write_file(".html")),
        'lint':
        (read_plain, register_docutils, lint_embedded_rst,
         write_file(".lint.json")),
        'rst':
        (read_plain, code_to_rst, write_file(".v.rst")),
    },
    'coqdoc': {
        'webpage':
        (read_plain, parse_plain, annotate_chunks, # transforms applied later
         gen_html_snippets_with_coqdoc, dump_html_standalone, copy_assets,
         write_file(".html")),
    },
    'rst': {
        'webpage':
        (read_plain, register_docutils, gen_rst_html, copy_assets,
         write_file(".html")),
        'lint':
        (read_plain, register_docutils, lint_rst, write_file(".lint.json")),
        'coq':
        (read_plain, rst_to_code, write_file(".v")),
        'coq+rst':
        (read_plain, rst_to_code, write_file(".v")),
    }
}

# CLI
# ===

EXTENSIONS = ['.v', '.lean', '.lean.json', '.v.json', '.json', '.v.rst', '.rst']
FRONTENDS_BY_EXTENSION = [
    ('.v', 'coq+rst'), ('.lean', 'lean3'),
    ('.v.json', 'coq.json'), ('.lean3.json', 'lean3.json'),
    ('.rst', 'rst')
]
BACKENDS_BY_EXTENSION = [
    ('.v', 'coq'), ('.lean', 'lean3'),
    ('.json', 'json'), ('.rst', 'rst'),
    ('.lint.json', 'lint'),
    ('.snippets.html', 'snippets-html'),
    ('.snippets.tex', 'snippets-latex'),
    ('.html', 'webpage')
]

DEFAULT_BACKENDS = {
    'coq.json': 'json',
    'lean3.json': 'json',
    'coq': 'webpage',
    'coqdoc': 'webpage',
    'coq+rst': 'webpage',
    'lean3': 'webpage',
    'rst': 'webpage'
}

INPUT_LANGUAGE_BY_FRONTEND = {
    "coq": "coq",
    "coqdoc": "coq",
    "coq+rst": "coq",
    "rst": None,
    "lean3": "lean3",
    "coq.json": "coq",
    "lean3.json": "lean3",
}

def infer_mode(fpath, kind, arg, table):
    for (ext, mode) in table:
        if fpath.endswith(ext):
            return mode
    MSG = """{}: Not sure what to do with {!r}.
Try passing {}?"""
    raise argparse.ArgumentTypeError(MSG.format(kind, fpath, arg))

def infer_frontend(fpath):
    return infer_mode(fpath, "input", "--frontend", FRONTENDS_BY_EXTENSION)

def infer_backend(frontend, out_fpath):
    if out_fpath:
        return infer_mode(out_fpath, "output", "--backend", BACKENDS_BY_EXTENSION)
    return DEFAULT_BACKENDS[frontend]

def resolve_pipeline(fpath, args):
    frontend = args.frontend or infer_frontend(fpath)
    backend = args.backend or infer_backend(frontend, args.output)
    supported_backends = PIPELINES[frontend]

    if backend not in supported_backends:
        MSG = """argument --backend: Frontend {!r} does not support backend {!r}: \
expecting one of {}"""
        raise argparse.ArgumentTypeError(MSG.format(
            frontend, backend, ", ".join(map(repr, supported_backends))))

    return (frontend, backend, supported_backends[backend])

COPY_FUNCTIONS = {
    "copy": shutil.copy,
    "symlink": os.symlink,
    "hardlink": os.link,
    "none": None
}

def post_process_arguments(parser, args):
    if len(args.input) > 1 and args.output:
        parser.error("argument --output: Not valid with multiple inputs")

    if args.stdin_filename and "-" not in args.input:
        parser.error("argument --stdin-filename: input must be '-'")

    for dirpath in args.coq_args_I:
        args.sertop_args.extend(("-I", dirpath))
    for pair in args.coq_args_R:
        args.sertop_args.extend(("-R", ",".join(pair)))
    for pair in args.coq_args_Q:
        args.sertop_args.extend(("-Q", ",".join(pair)))

    # argparse applies ‘type’ before ‘choices’, so we do the conversion here
    args.copy_fn = COPY_FUNCTIONS[args.copy_fn]

    args.point, args.marker = args.mark_point
    if args.point is not None:
        try:
            args.point = int(args.point)
        except ValueError:
            MSG = "argument --mark-point: Expecting a number, not {!r}"
            parser.error(MSG.format(args.point))

    args.lean3_args = ()

    args.html_assets = []
    args.html_classes = []
    args.pipelines = [(fpath, resolve_pipeline(fpath, args))
                      for fpath in args.input]

    return args

def build_parser():
    parser = argparse.ArgumentParser(description="""\
Annotate segments of Coq code with responses and goals.
Take input in Coq, reStructuredText, or JSON format \
and produce reStructuredText, HTML, or JSON output.""")

    INPUT_HELP = "Configure the input."
    out = parser.add_argument_group("Input arguments", INPUT_HELP)

    INPUT_FILES_HELP = "Input files"
    parser.add_argument("input", nargs="+", help=INPUT_FILES_HELP)

    INPUT_STDIN_NAME_HELP = "Name of file passed on stdin, if any"
    parser.add_argument("--stdin-filename", default=None,
                        help=INPUT_STDIN_NAME_HELP)

    FRONTEND_HELP = "Choose a frontend. Defaults: "
    FRONTEND_HELP += "; ".join("{!r} → {}".format(ext, frontend)
                               for ext, frontend in FRONTENDS_BY_EXTENSION)
    FRONTEND_CHOICES = sorted(PIPELINES.keys())
    out.add_argument("--frontend", default=None, choices=FRONTEND_CHOICES,
                     help=FRONTEND_HELP)


    OUTPUT_HELP = "Configure the output."
    out = parser.add_argument_group("Output arguments", OUTPUT_HELP)

    BACKEND_HELP = "Choose a backend. Supported: "
    BACKEND_HELP += "; ".join(
        "{} → {{{}}}".format(frontend, ", ".join(sorted(backends)))
        for frontend, backends in PIPELINES.items())
    BACKEND_CHOICES = sorted(set(b for _, bs in PIPELINES.items() for b in bs))
    out.add_argument("--backend", default=None, choices=BACKEND_CHOICES,
                     help=BACKEND_HELP)

    OUT_FILE_HELP = "Set the output file (default: computed based on INPUT)."
    parser.add_argument("-o", "--output", default=None,
                        help=OUT_FILE_HELP)

    OUT_DIR_HELP = "Set the output directory (default: same as each INPUT)."
    parser.add_argument("--output-directory", default=None,
                        help=OUT_DIR_HELP)

    COPY_ASSETS_HELP = ("Chose the method to use to copy assets " +
                        "along the generated file(s) when creating webpages.")
    parser.add_argument("--copy-assets", choices=list(COPY_FUNCTIONS.keys()),
                        default="copy", dest="copy_fn",
                        help=COPY_ASSETS_HELP)

    CACHE_DIRECTORY_HELP = ("Cache Coq's output in DIRECTORY.")
    parser.add_argument("--cache-directory", default=None, metavar="DIRECTORY",
                        help=CACHE_DIRECTORY_HELP)

    NO_HEADER_HELP = "Do not insert a header with usage instructions in webpages."
    parser.add_argument("--no-header", action='store_false',
                        dest="include_banner", default="True",
                        help=NO_HEADER_HELP)

    NO_VERSION_NUMBERS = "Omit version numbers in meta tags and headers."
    parser.add_argument("--no-version-numbers", action='store_false',
                        dest="include_vernums", default=True,
                        help=NO_VERSION_NUMBERS)

    WEBPAGE_STYLE_HELP = "Choose a style for standalone webpages."
    WEBPAGE_STYLE_CHOICES = ("centered", "floating", "windowed")
    parser.add_argument("--webpage-style", default="centered",
                        choices=WEBPAGE_STYLE_CHOICES,
                        help=WEBPAGE_STYLE_HELP)

    MARK_POINT_HELP = "Mark a point in the output with a given marker."
    parser.add_argument("--mark-point", nargs=2, default=(None, None),
                        metavar=("POINT", "MARKER"),
                        help=MARK_POINT_HELP)


    SUBP_HELP = "Pass arguments to the SerAPI process"
    subp = parser.add_argument_group("Subprocess arguments", SUBP_HELP)

    SERTOP_ARGS_HELP = "Pass a single argument to SerAPI (e.g. -Q dir,lib)."
    subp.add_argument("--sertop-arg", dest="sertop_args",
                      action="append", default=[],
                      metavar="SERAPI_ARG",
                      help=SERTOP_ARGS_HELP)

    I_HELP = "Pass -I DIR to the SerAPI subprocess."
    subp.add_argument("-I", "--ml-include-path", dest="coq_args_I",
                      metavar="DIR", nargs=1, action="append",
                      default=[], help=I_HELP)

    Q_HELP = "Pass -Q DIR COQDIR to the SerAPI subprocess."
    subp.add_argument("-Q", "--load-path", dest="coq_args_Q",
                      metavar=("DIR", "COQDIR"), nargs=2, action="append",
                      default=[], help=Q_HELP)

    R_HELP = "Pass -R DIR COQDIR to the SerAPI subprocess."
    subp.add_argument("-R", "--rec-load-path", dest="coq_args_R",
                      metavar=("DIR", "COQDIR"), nargs=2, action="append",
                      default=[], help=R_HELP)

    EXPECT_UNEXPECTED_HELP = "Ignore unexpected output from SerAPI"
    parser.add_argument("--expect-unexpected", action="store_true",
                        default=False, help=EXPECT_UNEXPECTED_HELP)

    DEBUG_HELP = "Print communications with prover process."
    parser.add_argument("--debug", action="store_true",
                        default=False, help=DEBUG_HELP)

    TRACEBACK_HELP = "Print error traces."
    parser.add_argument("--traceback", action="store_true",
                        default=False, help=TRACEBACK_HELP)

    return parser

def parse_arguments():
    parser = build_parser()
    return post_process_arguments(parser, parser.parse_args())


# Entry point
# ===========

def call_pipeline_step(step, state, ctx):
    params = list(inspect.signature(step).parameters.keys())[1:]
    return step(state, **{p: ctx[p] for p in params})

def build_context(fpath, frontend, backend, args):
    if fpath == "-":
        fname, fpath = "-", (args.stdin_filename or "-")
    else:
        fname = os.path.basename(fpath)

    ctx = {"fpath": fpath, "fname": fname, **vars(args)}
    ctx["frontend"], ctx["backend"] = frontend, backend
    ctx["input_language"] = INPUT_LANGUAGE_BY_FRONTEND[frontend]

    if args.output_directory is None:
        if fname == "-":
            ctx["output_directory"] = "."
        else:
            ctx["output_directory"] = os.path.dirname(os.path.abspath(fpath))

    return ctx

def except_hook(etype, value, tb):
    from traceback import TracebackException
    for line in TracebackException(etype, value, tb, capture_locals=True).format():
        print(line, file=sys.stderr)

def process_pipelines(args):
    if args.debug:
        from . import core
        core.DEBUG = True

    if args.traceback:
        from . import core
        core.TRACEBACK = True
        sys.excepthook = except_hook

    if args.cache_directory:
        from . import docutils
        docutils.CACHE_DIRECTORY = args.cache_directory

    if args.expect_unexpected:
        from . import serapi
        serapi.SerAPI.EXPECT_UNEXPECTED = True

    for fpath, (frontend, backend, pipeline) in args.pipelines:
        state, ctx = None, build_context(fpath, frontend, backend, args)
        for step in pipeline:
            state = call_pipeline_step(step, state, ctx)

def main():
    try:
        args = parse_arguments()
        process_pipelines(args)
    except (ValueError, FileNotFoundError, argparse.ArgumentTypeError) as e:
        from . import core
        if core.TRACEBACK:
            raise e
        print("Exiting early due to an error:", file=sys.stderr)
        print(str(e), file=sys.stderr)
        sys.exit(1)

# Alternative CLIs
# ================

def embedded_rst2html():
    from .docutils import RSTCoqStandaloneReader, RSTCoqParser
    DESCRIPTION = 'Build an HTML document from an Alectryon Coq file.'
    _docutils_cmdline(DESCRIPTION, RSTCoqStandaloneReader, RSTCoqParser)

def coqrst2html():
    from docutils.parsers.rst import Parser
    from docutils.readers.standalone import Reader
    DESCRIPTION = 'Build an HTML document from an Alectryon reStructuredText file.'
    _docutils_cmdline(DESCRIPTION, Reader, Parser)
