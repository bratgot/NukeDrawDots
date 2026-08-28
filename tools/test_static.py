#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_static.py
--------------
Import nuke_draw_dots.py against a given Nuke's bundled Qt and resolve every
Qt symbol it references, without ever constructing a QApplication.

This exists because Nuke's bundled python.exe hangs when it builds a
QApplication outside the application, which makes tools/test_import.py
unrunnable on the PySide2 versions (Nuke 14-15). Everything up to that point
still works, and that is enough to catch the failure this suite is really
looking for: a Qt name that exists in one PySide and not the other.

Run it with the interpreter beside each Nuke you support:

    "C:/Program Files/Nuke14.1v8/python.exe" tools/test_static.py
    "C:/Program Files/Nuke17.1v1/python.exe" tools/test_static.py
"""

from __future__ import print_function
import os
import ast
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
SRC = os.path.join(ROOT, "src", "nuke_draw_dots.py")
sys.path.insert(0, os.path.join(ROOT, "src"))

_failures = []


def check(name, condition, detail=""):
    if condition:
        print("  ok    {}".format(name))
    else:
        print("  FAIL  {} {}".format(name, detail))
        _failures.append(name)


def add_bundled_pyside():
    """Nuke's python.exe does not put its own site-packages on sys.path."""
    for name in ("PySide6", "PySide2"):
        try:
            __import__(name)
            return
        except ImportError:
            pass
    candidate = os.path.join(os.path.dirname(sys.executable),
                             "pythonextensions", "site-packages")
    if os.path.isdir(candidate):
        sys.path.append(candidate)


def stub_nuke():
    module = types.ModuleType("nuke")
    module.GUI = False              # suppresses the deferred auto-install
    module.nodes = types.SimpleNamespace()
    module.Undo = object
    module.zoom = lambda: 1.0
    module.center = lambda: (0.0, 0.0)
    module.allNodes = lambda: []
    module.selectedNodes = lambda: []
    sys.modules["nuke"] = module


add_bundled_pyside()
stub_nuke()

import nuke_draw_dots as dd  # noqa: E402  (must follow the stub)


# -- the symbol audit ------------------------------------------

_QT_MODULES = ("QtCore", "QtGui", "QtWidgets")


def _dotted(node):
    """Rebuild a QtCore.Qt.Foo chain from an ast.Attribute, or None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name) and node.id in _QT_MODULES:
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def referenced_symbols():
    """
    Every QtCore/QtGui/QtWidgets attribute chain the module actually uses.

    Parsed from the AST rather than matched with a regex: prose in a
    docstring ("pass a QtCore.Qt.Key_* constant") reads exactly like a real
    reference to a regex, and produced a false failure when it did.
    Walking the tree also yields the inner chains - QtCore.Qt as well as
    QtCore.Qt.Key_D - which are worth resolving too.
    """
    with open(SRC) as fh:
        tree = ast.parse(fh.read(), SRC)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted:
                found.add(dotted)
    return sorted(found)


def resolve(dotted):
    parts = dotted.split(".")
    obj = getattr(dd, parts[0])
    for part in parts[1:]:
        obj = getattr(obj, part)
    return obj


def test_binding():
    print("binding")
    check("a PySide binding was resolved", dd._PYSIDE_MAJOR in (2, 6),
          dd._PYSIDE_MAJOR)
    print("        Python {}.{}.{}, PySide{}, Qt {}".format(
        sys.version_info[0], sys.version_info[1], sys.version_info[2],
        dd._PYSIDE_MAJOR, dd.QtCore.qVersion()))

    # The two shims that exist purely to span Qt5 and Qt6. Drive
    # _global_pos with an event offering both APIs and see which it picks -
    # inspecting the bytecode cannot tell them apart, since both names
    # appear in the function either way.
    class BothApisEvent(object):
        def __init__(self):
            self.used = None

        def globalPosition(self):        # Qt6
            self.used = 6
            return dd.QtCore.QPointF(3.0, 4.0)

        def globalPos(self):             # Qt5
            self.used = 5
            return dd.QtCore.QPoint(1, 2)

    event = BothApisEvent()
    point = dd._global_pos(event)
    check("_global_pos calls the API this binding actually ships",
          event.used == (6 if dd._PYSIDE_MAJOR >= 6 else 5), event.used)
    check("_global_pos returns a QPoint",
          isinstance(point, dd.QtCore.QPoint), type(point))
    expected = (3, 4) if dd._PYSIDE_MAJOR >= 6 else (1, 2)
    check("_global_pos returns the right coordinates",
          (point.x(), point.y()) == expected, (point.x(), point.y()))

    check("QDialog exposes an exec the _exec shim can call",
          hasattr(dd.QtWidgets.QDialog, "exec_") or
          hasattr(dd.QtWidgets.QDialog, "exec"))


def test_symbols():
    print("Qt symbols referenced by the module")
    symbols = referenced_symbols()
    check("found symbols to audit", len(symbols) > 25, len(symbols))

    missing = []
    for dotted in symbols:
        try:
            resolve(dotted)
        except AttributeError as err:
            missing.append("{} ({})".format(dotted, err))

    check("every Qt symbol resolves under this binding",
          not missing, "\n        " + "\n        ".join(missing))
    print("        audited {} symbols".format(len(symbols)))


def test_classes():
    print("widget classes")
    check("_PathOverlay is a QWidget",
          issubclass(dd._PathOverlay, dd.QtWidgets.QWidget))
    check("_SimplifyDialog is a QDialog",
          issubclass(dd._SimplifyDialog, dd.QtWidgets.QDialog))
    check("_Filter is a QObject",
          issubclass(dd._Filter, dd.QtCore.QObject))
    # Class-body attributes are evaluated at import, so a bad QColor call
    # would already have raised - assert they arrived intact.
    check("overlay colours built",
          all(isinstance(getattr(dd._PathOverlay, n), dd.QtGui.QColor)
              for n in ("RAW_COLOUR", "PATH_COLOUR", "DOT_COLOUR",
                        "OUTLINE_COLOUR")))


def test_geometry_through_module():
    """The maths, run through the real import rather than an exec'd copy."""
    print("geometry via the imported module")

    line = [(float(i), 0.0) for i in range(50)]
    check("straight drag simplifies to 2 points",
          len(dd.simplify_path(line, 12.0, True, 0)) == 2)

    stroke = [(float(i) * 2.0, 0.0) for i in range(60)]
    stroke += [(118.0, float(i) * 2.0) for i in range(60)]
    square = dd.simplify_path(stroke, 12.0, True, 16)
    check("an L simplifies to 3 points", len(square) == 3, square)
    check("right angles hold",
          all(abs(b[0] - a[0]) < 1e-6 or abs(b[1] - a[1]) < 1e-6
              for a, b in zip(square, square[1:])), square)
    check("grid snapping holds",
          all(abs(v % 16) < 1e-6 for p in square for v in p), square)
    check("degenerate input is safe",
          dd.simplify_path([], 12.0, True, 16) == [] and
          len(dd.simplify_path([(1.0, 1.0)], 12.0, True, 16)) < 2)


def test_no_side_effects():
    print("import hygiene")
    check("no event filter installed on import", dd._filter is None)
    check("prefs fall back to the defaults when no file exists",
          set(dd._prefs_get()) == set(dd._DEFAULT_PREFS))


def main():
    for test in (test_binding, test_symbols, test_classes,
                 test_geometry_through_module, test_no_side_effects):
        test()
        print("")

    if _failures:
        print("{} FAILED: {}".format(len(_failures), ", ".join(_failures)))
        return 1
    print("all static tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
