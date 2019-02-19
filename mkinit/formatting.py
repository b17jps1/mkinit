"""
Contains logic for formatting statically / dynamically extracted information
into the final product.
"""
from __future__ import absolute_import, division, print_function, unicode_literals
from os.path import join, exists
import textwrap
import logging
from mkinit import static_analysis as static


logger = logging.getLogger(__name__)


def _ensure_options(given_options=None):
    """
    Ensures dict contains all formatting options.

    Defaults are:
        with_attrs (bool): if True, generate module attribute from imports
            (Default: True)
        with_mods (bool): if True, generate module imports
            (Default: True)
        with_all (bool): if True, generate an __all__ variable
            (Default: True)
        relative (bool): if True, generate relative `.` imports
            (Default: False)

    """
    if given_options is None:
        given_options = {}
    default_options = {
        'with_attrs': True,
        'with_mods': True,
        'with_all': True,
        'relative': False,
    }
    options = default_options.copy()
    for k in given_options.keys():
        if k not in default_options:
            raise KeyError('options got bad key={}'.format(k))
    options.update(given_options)
    return options


def _insert_autogen_text(modpath, initstr):
    """
    Creates new text for `__init__.py` containing the autogenerated code.

    If an `__init__.py` already exists in `modpath`, then it tries to
    intelligently insert the code without clobbering too much. See
    `_find_insert_points` for details on this process.
    """

    # Get path to init file so we can overwrite it
    init_fpath = join(modpath, '__init__.py')
    logger.debug('inserting initstr into: {!r}'.format(init_fpath))

    if exists(init_fpath):
        with open(init_fpath, 'r') as file_:
            lines = file_.readlines()
    else:
        lines = []

    startline, endline, init_indent = _find_insert_points(lines)
    initstr_ = _indent(initstr, init_indent) + '\n'

    new_lines = lines[:startline] + [initstr_] + lines[endline:]

    new_text = ''.join(new_lines).rstrip() + '\n'
    return init_fpath, new_text


def _find_insert_points(lines):
    r"""
    Searches for the points to insert autogenerated text between.

    If the `# <AUTOGEN_INIT>` directive exists, then it is preserved and new
    text is inserted after it. This text clobbers all other text until the `#
    <AUTOGEN_INIT>` is reached.

    If the explicit tags are not specified, mkinit will only clobber text after
    one of these patterns:
        * A line beginning with a (#) comment
        * A multiline (triple-quote) comment
        * A line beginning with "from __future__"
        * A line beginning with "__version__"

    If neither explicit tags or implicit patterns exist, all text is clobbered.

    Args:
        lines (list): lines of an `__init__.py` file.

    Returns:
        tuple: (int, int, str):
            insert points as starting line, ending line, and any required
            indentation.

    Examples:
        >>> lines = textwrap.dedent(
            '''
            preserved1 = True
            if True:
                # <AUTOGEN_INIT>
                clobbered2 = True
                # </AUTOGEN_INIT>
            preserved3 = True
            ''').strip('\n').split('\n')
        >>> start, end, indent = _find_insert_points(lines)
        >>> print(repr((start, end, indent)))
        (3, 4, '    ')

    Examples:
        >>> lines = textwrap.dedent(
            '''
            preserved1 = True
            __version__ = '1.0'
            clobbered2 = True
            ''').strip('\n').split('\n')
        >>> start, end, indent = _find_insert_points(lines)
        >>> print(repr((start, end, indent)))
        (2, 3, '')
    """
    startline = 0
    endline = len(lines)
    explicit_flag = False
    init_indent = ''

    # co-opt the xdoctest parser to break appart lines in the init file
    # This lets us correctly skip to the end of a multiline expression
    # A better solution might be to use the line-number aware parser
    # to search for AUTOGEN_INIT comments and other relevant structures.
    source_lines = ['>>> ' + p.rstrip('\n') for p in lines]
    try:
        ps1_lines, _ = static._locate_ps1_linenos(source_lines)
        # print('ps1_lines = {!r}'.format(ps1_lines))
    except IndexError:
        assert len(lines) == 0
        ps1_lines = []

    # Algorithm is similar to the old version, but we skip to the next PS1
    # line if we encounter an implicit code pattern.

    skipto = None

    def _tryskip(lineno):
        """ returns the next line to skip to if possible """

    implicit_patterns = (
        'from __future__', '__version__', '__submodules__',

        '__external__',
        '__private__',
        '__protected__',

        '#', '"""', "'''",
    )
    for lineno, line in enumerate(lines):
        if skipto is not None:
            if lineno != skipto:
                continue
            else:
                # print('SKIPPED TO = {!r}'.format(lineno))
                skipto = None
        if not explicit_flag:
            if line.strip().startswith(implicit_patterns):
                # print('[mkinit] RESPECTING LINE {}: {}'.format(lineno, line))
                startline = lineno + 1
                try:
                    # Try and skip to the end of the expression
                    # (if it is a multiline case)
                    idx = ps1_lines.index(lineno)
                    skipto = ps1_lines[idx + 1]
                    startline = skipto
                    # print('SKIPTO = {!r}'.format(skipto))
                except ValueError:
                    # print('NOT ON A PS1 LINE KEEP {}'.format(startline))
                    pass
                except IndexError:
                    # print('LAST LINE MOVING TO END {}'.format(startline))
                    startline = endline
        if line.strip().startswith('# <AUTOGEN_INIT>'):  # allow tags too
            # print('[mkinit] FOUND START TAG ON LINE {}: {}'.format(lineno, line))
            init_indent = line[:line.find('#')]
            explicit_flag = True
            startline = lineno + 1
        if explicit_flag and line.strip().startswith('# </AUTOGEN_INIT>'):
            # print('[mkinit] FOUND END TAG ON LINE {}: {}'.format(lineno, line))
            endline = lineno

    # print('startline = {}'.format(startline))
    # print('endline = {}'.format(endline))
    assert startline <= endline
    return startline, endline, init_indent


def _indent(text, indent='    '):
    new_text = indent + text.replace('\n', '\n' + indent)
    # remove whitespace on blank lines
    new_text = '\n'.join([line.rstrip() for line in new_text.split('\n')])
    return new_text


def _initstr(modname, imports, from_imports, explicit=set(), protected=set(),
             private=set(), options=None):
    """
    Calls the other string makers

    CommandLine:
        python -m mkinit.static_autogen _initstr

    Args:
        options (dict): customize output

    CommandLine:
        python -m mkinit.formatting _initstr

    Example:
        >>> modname = 'foo'
        >>> imports = ['.bar', '.baz']
        >>> from_imports = [('.bar', ['func1', 'func2'])]
        >>> initstr = _initstr(modname, imports, from_imports)
        >>> print(initstr)
        from foo import bar
        from foo import baz
        <BLANKLINE>
        from foo.bar import (func1, func2,)
        <BLANKLINE>
        __all__ = ['bar', 'baz', 'func1', 'func2']

    Example:
        >>> modname = 'foo'
        >>> imports = ['.bar', '.baz']
        >>> from_imports = [('.bar', list(map(chr, range(97, 123))))]
        >>> initstr = _initstr(modname, imports, from_imports)
        >>> print(initstr)
        from foo import bar
        from foo import baz
        <BLANKLINE>
        from foo.bar import (a, b, c, d, e, f, g, h, i, j, k, l, m, n, o, p, q, r, s,
                             t, u, v, w, x, y, z,)
        <BLANKLINE>
        __all__ = ['a', 'b', 'bar', 'baz', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k',
                   'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x',
                   'y', 'z']
    """
    options = _ensure_options(options)

    if options['relative']:
        modname = '.'

    explicit_exports = list(explicit)
    parts = []
    # if options.get('with_header', False):
    #     parts.append(_make_module_header())

    def append_part(new_part):
        """ appends a new part if it is nonempty """
        if new_part:
            if parts:
                # separate from previous parts with a newline
                parts.append('')
            parts.append(new_part)

    if options.get('with_mods', True):
        explicit_exports.extend([e.lstrip('.') for e in imports])
        append_part(_make_imports_str(imports, modname))

    if options.get('with_attrs', True):
        from fnmatch import fnmatch
        # TODO: allow pattern matching here
        # step1: separate into explicit vs glob-pattern strings
        private = set(private)
        private_pats =  {p for p in private if '*' in p}
        private_set = private - private_pats

        protected = set(protected)
        protected_pats =  {p for p in protected if '*' in p}
        protected_set = protected - protected_pats

        _pp_pats = protected_pats | private_pats
        _pp_set = private_set | protected_set

        def _pp_matches(x):
            # TODO: standardize how explicit vs submodules are handled
            x = x.lstrip('.')
            return x in _pp_set or any(fnmatch(x, pat) for pat in _pp_pats)

        def _private_matches(x):
            x = x.lstrip('.')
            return x in private_set or any(fnmatch(x, pat) for pat in private_pats)

        _from_imports = [
            (m, sub) for m, sub in from_imports if not _pp_matches(m)
        ]

        explicit_exports.extend([
            n for m, sub in _from_imports for n in sub
            if not _private_matches(n)
        ])
        attr_part = _make_fromimport_str(_from_imports, modname)
        append_part(attr_part)

    if options.get('with_all', True):
        exports_repr = ["'{}'".format(e)
                        for e in sorted(explicit_exports)]
        rhs_body = ', '.join(exports_repr)
        packed = _packed_rhs_text('__all__ = [', rhs_body + ']')
        append_part(packed)

    initstr = '\n'.join([p for p in parts])
    return initstr


# def _make_module_header():
#     return '\n'.join([
#         '# flake8:' + ' noqa',  # the plus prevents it from triggering on this file
#         'from __future__ import absolute_import, division, print_function, unicode_literals'])


def _make_imports_str(imports, rootmodname='.'):
    if False:
        imports_fmtstr = 'from {rootmodname} import %s'.format(
            rootmodname=rootmodname)
        return '\n'.join([imports_fmtstr % (name,) for name in imports])
    else:
        imports_fmtstr = 'from {rootmodname} import %s'.format(
            rootmodname=rootmodname)
        return '\n'.join([
            imports_fmtstr % (name.lstrip('.'))
            if name.startswith('.') else
            'import %s' % (name,)
            for name in imports
        ])


def _packed_rhs_text(lhs_text, rhs_text):
    """ packs rhs text to have indentation that agrees with lhs text """
    # not sure why this isn't 76? >= maybe?
    newline_prefix = (' ' * len(lhs_text))
    raw_text = lhs_text + rhs_text
    packstr = '\n'.join(textwrap.wrap(raw_text, break_long_words=False,
                                      width=79, initial_indent='',
                                      subsequent_indent=newline_prefix))
    return packstr


def _make_fromimport_str(from_imports, rootmodname='.', indent=''):
    """
    Args:
        from_imports (list): each item is a tuple with module and a list of
            imported with_attrs.
        rootmodname (str): name of root module
        indent (str): initial indentation

    Example:
        >>> from_imports = [
        ...     ('.foo', list(map(chr, range(97, 123)))),
        ...     ('.bar', []),
        ...     ('.a_longer_package', list(map(chr, range(65, 91)))),
        ... ]
        >>> from_str = _make_fromimport_str(from_imports, indent=' ' * 8)
        >>> print(from_str)
        from .foo import (a, b, c, d, e, f, g, h, i, j, k, l, m, n, o, p, q, r,
                          s, t, u, v, w, x, y, z,)
        from .a_longer_package import (A, B, C, D, E, F, G, H, I, J, K, L, M,
                                       N, O, P, Q, R, S, T, U, V, W, X, Y, Z,)
    """
    if rootmodname == '.':  # nocover
        # dot is already taken care of in fmtstr
        rootmodname = ''
    def _pack_fromimport(tup):
        name, fromlist = tup[0], tup[1]

        if name.startswith('.'):
            normname = rootmodname + name
        else:
            normname = name

        if len(fromlist) > 0:
            lhs_text = indent + 'from {normname} import ('.format(
                normname=normname)
            rhs_text = ', '.join(fromlist) + ',)'
            packstr = _packed_rhs_text(lhs_text, rhs_text)
        else:
            packstr = ''
        return packstr

    parts = [_pack_fromimport(t) for t in from_imports]
    from_str = '\n'.join([p for p in parts if p])
    # Return unindented version for now
    from_str = textwrap.dedent(from_str)
    return from_str


if __name__ == '__main__':
    """
    CommandLine:
        python -m mkinit.formatting all
    """
    import xdoctest
    xdoctest.doctest_module(__file__)
