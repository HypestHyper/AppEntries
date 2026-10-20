"""Checks on the source code itself."""
import ast
import pathlib

PKG = pathlib.Path(__file__).resolve().parent.parent / "app_entries"


def test_no_function_shadows_the_translation_function():
    """A handler written `def f(self, *_)` that calls _("…") fails at run time,
    and GTK swallows the error, so the button just does nothing."""
    bad = []
    for path in PKG.rglob("*.py"):
        for fn in ast.walk(ast.parse(path.read_text())):
            if not isinstance(fn, (ast.FunctionDef, ast.Lambda)):
                continue
            a = fn.args
            names = [x.arg for x in a.args + a.kwonlyargs] + [v.arg for v in (a.vararg, a.kwarg) if v]
            if "_" not in names:
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_":
                    bad.append("%s:%d" % (path.relative_to(PKG.parent), fn.lineno))
                    break
    assert bad == []
