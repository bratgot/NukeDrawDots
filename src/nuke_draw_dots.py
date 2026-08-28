# -*- coding: utf-8 -*-
"""
nuke_draw_dots.py
-----------------
Nuke 14.1-17.1 - press Shift+D in the Node Graph and drag to draw a freehand
path. On release a small panel lets you simplify the path and snap it to right
angles, with a live preview drawn over the DAG. Accept and the path is
committed as a chain of connected Dot nodes.

If the stroke starts on a node, the first Dot is wired to that node's output.
If it ends on a node, that node's first input is wired to the last Dot.

Qt bindings are auto-detected: PySide6 (Nuke 16+), PySide2 (Nuke 14-15).

Install:  drop into ~/.nuke/ and add to menu.py:
              import nuke_draw_dots

Debug:    set DEBUG = True and watch the Script Editor for [DD] lines.
"""

from __future__ import print_function
import json
import math
import os
import sys
import traceback

import nuke

__version__ = "1.0.0"

# -- Qt binding ------------------------------------------------
#
# PySide6 (Qt6) -> Nuke 16+
# PySide2 (Qt5) -> Nuke 14-15

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    _PYSIDE_MAJOR = 6
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    _PYSIDE_MAJOR = 2


def _global_pos(event):
    """Return a mouse event's global position as QPoint - Qt5 and Qt6."""
    if _PYSIDE_MAJOR >= 6:
        return event.globalPosition().toPoint()
    return event.globalPos()


def _exec(dialog):
    """QDialog.exec_() under PySide2, exec() under strict PySide6 builds."""
    if hasattr(dialog, "exec_"):
        return dialog.exec_()
    return dialog.exec()


# -- Config ----------------------------------------------------

SHORTCUT_KEY      = QtCore.Qt.Key_D
REQUIRE_MODIFIER  = QtCore.Qt.ShiftModifier

MIN_SAMPLE_PX     = 3      # Screen px a stroke must travel before resampling
MIN_POINTS        = 2      # Fewer than this after simplifying = create nothing

DEFAULT_TOLERANCE = 12     # Simplify strength, in DAG units
DEFAULT_ORTHO     = True   # Start with right angles on
DEFAULT_SNAP      = False  # Start with grid snapping off
DEFAULT_GRID      = 16     # Grid size in DAG units
MAX_TOLERANCE     = 150

CONNECT_ENDS      = True   # Wire the chain into nodes under the stroke ends
CONNECT_RADIUS    = 45     # How near an end must be to a node, in DAG units

DOT_SIZE          = 12     # Fallback Dot width when screenWidth() reads 0
UNDO_NAME         = "Draw Dots"

DEBUG             = False

# Last-used panel settings, remembered across Nuke sessions.
PREFS_FILE = os.path.join(os.path.expanduser("~"), ".nuke",
                          "nuke_draw_dots_prefs.json")


def _log(msg):
    if DEBUG:
        print("[DD] {}".format(msg))


# -- Prefs -----------------------------------------------------

_DEFAULT_PREFS = {
    "tolerance": DEFAULT_TOLERANCE,
    "ortho":     DEFAULT_ORTHO,
    "snap":      DEFAULT_SNAP,
    "grid":      DEFAULT_GRID,
    "connect":   CONNECT_ENDS,
}


def _prefs_get():
    prefs = dict(_DEFAULT_PREFS)
    try:
        with open(PREFS_FILE, "r") as fh:
            saved = json.load(fh)
        for key in prefs:
            if key in saved:
                prefs[key] = saved[key]
    except Exception:
        pass
    return prefs


def _prefs_save(prefs):
    try:
        folder = os.path.dirname(PREFS_FILE)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(PREFS_FILE, "w") as fh:
            json.dump(prefs, fh, indent=2)
    except Exception:
        _log("could not write prefs:\n{}".format(traceback.format_exc()))


# -- geometry - BEGIN ------------------------------------------
#
# Everything between the BEGIN/END markers is pure maths on lists of
# (x, y) tuples - no Nuke and no Qt. tools/test_geometry.py execs this
# region directly so the shipped code is what gets tested.


def _point_line_distance(p, a, b):
    """Perpendicular distance from p to the segment a->b."""
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    seg = dx * dx + dy * dy
    if seg <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / seg
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _rdp(points, epsilon):
    """
    Ramer-Douglas-Peucker.

    Iterative rather than recursive - a long freehand stroke can be a few
    thousand samples and the recursive form trips Python's stack limit.
    """
    n = len(points)
    if n < 3 or epsilon <= 0.0:
        return list(points)

    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]

    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        far_d, far_i = -1.0, i0
        a, b = points[i0], points[i1]
        for i in range(i0 + 1, i1):
            d = _point_line_distance(points[i], a, b)
            if d > far_d:
                far_d, far_i = d, i
        if far_d > epsilon:
            keep[far_i] = True
            stack.append((i0, far_i))
            stack.append((far_i, i1))

    return [p for p, k in zip(points, keep) if k]


def _orthogonalise(points):
    """
    Snap every segment to horizontal or vertical, whichever it is already
    closer to. Each new point is measured against the point already placed,
    so the result is a connected staircase with no gaps.
    """
    if len(points) < 2:
        return list(points)
    out = [points[0]]
    for x, y in points[1:]:
        px, py = out[-1]
        if abs(x - px) >= abs(y - py):
            out.append((x, py))
        else:
            out.append((px, y))
    return out


def _snap_to_grid(points, grid):
    """Round every coordinate to the nearest multiple of grid."""
    if grid <= 0:
        return list(points)
    g = float(grid)
    return [(round(x / g) * g, round(y / g) * g) for x, y in points]


def _dedupe(points, min_dist=0.5):
    """Drop points that land on top of the one before them."""
    if not points:
        return []
    out = [points[0]]
    for p in points[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > min_dist:
            out.append(p)
    return out


def _drop_collinear(points, tol=0.5):
    """
    Remove interior points that sit on the line between their neighbours.
    Orthogonalising often produces runs of points along one axis; without
    this each one would become a redundant Dot.
    """
    if len(points) < 3:
        return list(points)
    out = [points[0]]
    for i in range(1, len(points) - 1):
        if _point_line_distance(points[i], out[-1], points[i + 1]) > tol:
            out.append(points[i])
    out.append(points[-1])
    return out


def simplify_path(points, tolerance=0.0, orthogonal=False, grid=0):
    """
    Full pipeline: dedupe -> RDP -> right angles -> grid -> tidy.

    Order matters. Right angles are applied after RDP so the staircase is
    built from corners the user actually drew, and the grid is applied last
    because snapping a horizontal segment moves both its ends to the same
    row, so the right angles survive it.
    """
    pts = _dedupe(points, 0.5)
    if len(pts) < 2:
        return pts
    pts = _rdp(pts, float(tolerance))
    if orthogonal:
        pts = _orthogonalise(pts)
    if grid and grid > 0:
        pts = _snap_to_grid(pts, grid)
    pts = _dedupe(pts, 0.5)
    return _drop_collinear(pts, 0.5)


# -- geometry - END --------------------------------------------


# -- DAG geometry ----------------------------------------------

# Substrings that mark a widget as part of a Node Graph, tested against
# both its class name and its object name. Nuke names these differently
# between versions, so the list is deliberately broad.
DAG_TAGS = ("dag", "nodegraph", "nodeeditor", "grapheditor",
            "qglwidget", "qopenglwidget")


def _widget_is_live(widget):
    """
    True if the C++ object behind a Python widget wrapper still exists.

    Nuke 14.1 hands back wrappers for destroyed QGLWidgets from
    QApplication.widgetAt(). Such a wrapper still answers metaObject(),
    so a class-name test says "yes, a Node Graph" and the next call - here
    it was width() - raises RuntimeError. Check liveness before trusting
    any widget that came from a lookup.
    """
    if widget is None:
        return False
    try:
        widget.width()
        return True
    except RuntimeError:
        return False


def _dag_match(widget, max_depth=30):
    """
    Why widget counts as a Node Graph, or None if it does not.

    Returns a description rather than a bool so diagnose() can report what
    actually matched - when this tool fails to arm, the answer is nearly
    always that nothing here matched and the reason needs to be visible.

    max_depth=1 tests the widget itself only, ignoring its ancestors.
    """
    w = widget
    for depth in range(max_depth):
        if w is None:
            break
        try:
            cls = w.metaObject().className()
            name = w.objectName()
        except RuntimeError:
            break
        for tag in DAG_TAGS:
            if tag in cls.lower() or tag in name.lower():
                return "{}({}) matched '{}' at depth {}".format(
                    cls, name or "-", tag, depth)
        if hasattr(w, "windowTitle"):
            try:
                if "node graph" in w.windowTitle().lower():
                    return "window title 'Node Graph' at depth {}".format(
                        depth)
            except RuntimeError:
                break
        w = w.parentWidget()
    return None


def _is_dag_widget(widget):
    """True if widget, or any ancestor, looks like a Node Graph panel."""
    return _dag_match(widget) is not None


def _describe(widget):
    """Class and object name of a widget, for the debug trace."""
    if widget is None:
        return "None"
    try:
        return "{}({})".format(widget.metaObject().className(),
                               widget.objectName() or "-")
    except RuntimeError:
        return "(deleted)"


def _capture_dag_rect(widget):
    """
    Snapshot a widget's global rect as plain numbers, or None if the
    widget dies while being read.

    Numbers rather than a widget reference is the whole point. Nuke 14.1
    destroys the Node Graph's QGLWidget out from under us, and a reference
    held across any call back into Nuke - nuke.zoom() is enough - can be
    dead by the time it is next touched.
    """
    try:
        width = float(widget.width())
        height = float(widget.height())
        top_left = widget.mapToGlobal(QtCore.QPoint(0, 0))
        return (float(top_left.x()), float(top_left.y()), width, height)
    except RuntimeError:
        return None


def _search_dag_widgets(global_point):
    """
    Every live Node Graph widget containing global_point, largest first.

    Only widgets whose own class or object name carries a DAG tag count -
    ancestor matches would also catch the panel's title bar and the little
    overlay buttons, which are the wrong size to measure a stroke against.
    """
    app = QtWidgets.QApplication.instance()
    if app is None:
        return []

    found = []
    for w in app.allWidgets():
        try:
            if not w.isVisible() or not _widget_is_live(w):
                continue
            if _dag_match(w, max_depth=1) is None:
                continue
            top_left = w.mapToGlobal(QtCore.QPoint(0, 0))
            if not QtCore.QRect(top_left, w.size()).contains(global_point):
                continue
            found.append((w.width() * w.height(), w))
        except RuntimeError:
            continue
    found.sort(key=lambda pair: pair[0], reverse=True)
    return [w for _area, w in found]


def _dag_candidates(global_point):
    """
    Widgets that might be the Node Graph under global_point, best first.

    More than one is offered because any of them can be destroyed between
    being found and being measured; the caller tries each until a
    measurement succeeds.
    """
    candidates = []
    under = QtWidgets.QApplication.widgetAt(global_point)
    live = _widget_is_live(under)
    _log("resolve: under cursor={} (live={})".format(_describe(under), live))

    if live:
        if not _is_dag_widget(under):
            # A live widget that is not a Node Graph means the click
            # genuinely landed in another panel. Searching on would resolve
            # to whichever DAG holds focus and measure the stroke against a
            # panel the user was not pointing at.
            return []
        candidates.append(under)

    candidates.extend(_search_dag_widgets(global_point))

    # Only useful when the shortcut was used - focus is the Script Editor
    # whenever arm() was called from there.
    focus = QtWidgets.QApplication.focusWidget()
    if _widget_is_live(focus) and _is_dag_widget(focus):
        candidates.append(focus)

    unique = []
    seen = set()
    for widget in candidates:
        if id(widget) not in seen:
            seen.add(id(widget))
            unique.append(widget)
    return unique


def _resolve_dag_rect(global_point):
    """
    The global rect a stroke starting at global_point is measured against,
    as (x, y, width, height), or None if no live Node Graph is there.

    Returns numbers, never a widget: see _capture_dag_rect.
    """
    for widget in _dag_candidates(global_point):
        rect = _capture_dag_rect(widget)
        if rect is not None and rect[2] > 1.0 and rect[3] > 1.0:
            _log("  measured against {} rect={}".format(
                _describe(widget), rect))
            return rect
        _log("  {} died or had no size - trying the next candidate"
             .format(_describe(widget)))
    return None


class _DagTransform(object):
    """
    Screen <-> DAG mapping, frozen at mouse-down.

    A freehand stroke wanders outside the DAG widget, where
    QApplication.widgetAt() returns something else entirely and the mapping
    falls apart. So the rect, and the current zoom/centre, are captured
    once and every sample is mapped through that rather than re-resolving
    per point.

    Takes a plain (x, y, width, height) tuple, never a widget. Nuke 14.1
    destroys the Node Graph's QGLWidget during ordinary work, and calling
    nuke.zoom() while holding a reference to it was enough to get the
    widget deleted before its size could be read.
    """

    def __init__(self, rect):
        self.gx, self.gy, self.w, self.h = rect

        zoom = nuke.zoom()
        if isinstance(zoom, (list, tuple)):
            zoom = zoom[0]
        self.zoom = max(float(zoom or 1.0), 0.001)

        try:
            centre = nuke.center()
            self.cx, self.cy = float(centre[0]), float(centre[1])
        except Exception:
            self.cx, self.cy = 0.0, 0.0

        _log("transform: zoom={:.3f} centre=({:.0f},{:.0f}) "
             "size={:.0f}x{:.0f} origin=({:.0f},{:.0f})".format(
                 self.zoom, self.cx, self.cy, self.w, self.h,
                 self.gx, self.gy))

    def global_to_local(self, point):
        return (point.x() - self.gx, point.y() - self.gy)

    def local_to_dag(self, lx, ly):
        return (self.cx + (lx - self.w / 2.0) / self.zoom,
                self.cy + (ly - self.h / 2.0) / self.zoom)

    def dag_to_local(self, x, y):
        return ((x - self.cx) * self.zoom + self.w / 2.0,
                (y - self.cy) * self.zoom + self.h / 2.0)

    def global_rect(self):
        return QtCore.QRect(int(self.gx), int(self.gy),
                            int(self.w), int(self.h))


def _node_rect(node):
    w = node.screenWidth() or 80
    h = node.screenHeight() or 18
    return node.xpos(), node.ypos(), w, h


def _node_near(x, y, radius, need_input=False):
    """
    Nearest node whose box is within radius of the DAG point (x, y).

    Backdrops and sticky notes are skipped - a stroke drawn across a
    backdrop is aimed at the nodes inside it, not at the backdrop.
    """
    best, best_d = None, None
    try:
        nodes = nuke.allNodes()
    except Exception:
        return None

    for node in nodes:
        cls = node.Class()
        if cls in ("BackdropNode", "StickyNote"):
            continue
        try:
            if need_input:
                if node.maxInputs() < 1:
                    continue
            elif cls == "Viewer":
                continue
            nx, ny, nw, nh = _node_rect(node)
        except Exception:
            continue
        dx = max(nx - x, 0.0, x - (nx + nw))
        dy = max(ny - y, 0.0, y - (ny + nh))
        d = math.hypot(dx, dy)
        if d <= radius and (best_d is None or d < best_d):
            best, best_d = node, d
    return best


# -- Preview overlay -------------------------------------------

class _PathOverlay(QtWidgets.QWidget):
    """
    Frameless translucent top-level widget covering the DAG, painting the
    raw stroke and the simplified preview on top of it.

    WA_TransparentForMouseEvents is essential - without it the overlay eats
    the drag it is meant to be following.
    """

    RAW_COLOUR     = QtGui.QColor(190, 190, 190, 90)
    PATH_COLOUR    = QtGui.QColor(255, 176, 64, 235)
    DOT_COLOUR     = QtGui.QColor(255, 210, 140, 255)
    OUTLINE_COLOUR = QtGui.QColor(30, 30, 30, 200)

    def __init__(self, zoom=1.0):
        super(_PathOverlay, self).__init__(None)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._zoom = zoom
        self._raw = []
        self._path = []
        self._show_dots = False

    def set_raw(self, points):
        self._raw = points
        self.update()

    def set_path(self, points):
        self._path = points
        self._show_dots = True
        self.update()

    @staticmethod
    def _polygon(points):
        return QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in points])

    def paintEvent(self, event):
        if not self._raw and not self._path:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setBrush(QtCore.Qt.NoBrush)

        if len(self._raw) > 1:
            pen = QtGui.QPen(self.RAW_COLOUR)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawPolyline(self._polygon(self._raw))

        if len(self._path) > 1:
            pen = QtGui.QPen(self.PATH_COLOUR)
            pen.setWidth(2)
            pen.setJoinStyle(QtCore.Qt.MiterJoin)
            painter.setPen(pen)
            painter.drawPolyline(self._polygon(self._path))

        if self._show_dots:
            radius = max(2.5, DOT_SIZE * self._zoom * 0.5)
            pen = QtGui.QPen(self.OUTLINE_COLOUR)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(self.DOT_COLOUR))
            for x, y in self._path:
                painter.drawEllipse(QtCore.QPointF(x, y), radius, radius)

        painter.end()


# -- Simplify panel --------------------------------------------

class _SimplifyDialog(QtWidgets.QDialog):
    """
    Simplify / right-angle controls, with a live preview on the overlay.

    Also flagged WindowStaysOnTop: the overlay is topmost, and without the
    same hint this panel would be painted underneath it.
    """

    def __init__(self, raw_dag, transform, overlay,
                 start_node=None, end_node=None, parent=None):
        super(_SimplifyDialog, self).__init__(parent)
        self.setWindowTitle("Draw Dots")
        self.setWindowFlags(self.windowFlags() |
                            QtCore.Qt.WindowStaysOnTopHint)

        self._raw = raw_dag
        self._xform = transform
        self._overlay = overlay
        self._start_node = start_node
        self._end_node = end_node
        self.points = list(raw_dag)

        prefs = _prefs_get()

        form = QtWidgets.QGridLayout()
        form.setContentsMargins(12, 12, 12, 8)
        form.setHorizontalSpacing(8)

        # Simplify
        self._slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._slider.setRange(0, MAX_TOLERANCE)
        self._slider.setValue(int(prefs["tolerance"]))
        self._slider.setMinimumWidth(200)
        self._tol_label = QtWidgets.QLabel()
        self._tol_label.setMinimumWidth(28)
        form.addWidget(QtWidgets.QLabel("Simplify"), 0, 0)
        form.addWidget(self._slider, 0, 1)
        form.addWidget(self._tol_label, 0, 2)

        # Right angles
        self._ortho = QtWidgets.QCheckBox("Right angles")
        self._ortho.setChecked(bool(prefs["ortho"]))
        self._ortho.setToolTip(
            "Snap every segment to horizontal or vertical.")
        form.addWidget(self._ortho, 1, 1, 1, 2)

        # Grid
        grid_row = QtWidgets.QHBoxLayout()
        self._snap = QtWidgets.QCheckBox("Snap to grid")
        self._snap.setChecked(bool(prefs["snap"]))
        self._grid = QtWidgets.QSpinBox()
        self._grid.setRange(2, 200)
        self._grid.setValue(int(prefs["grid"]))
        self._grid.setEnabled(self._snap.isChecked())
        grid_row.addWidget(self._snap)
        grid_row.addWidget(self._grid)
        grid_row.addStretch(1)
        form.addLayout(grid_row, 2, 1, 1, 2)

        # Connect ends
        self._connect = QtWidgets.QCheckBox(self._connect_label())
        self._connect.setChecked(bool(prefs["connect"]))
        self._connect.setEnabled(bool(start_node or end_node))
        form.addWidget(self._connect, 3, 1, 1, 2)

        self._count = QtWidgets.QLabel()
        form.addWidget(self._count, 4, 1, 1, 2)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        ok_button = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        ok_button.setText("Create")
        ok_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._slider.valueChanged.connect(self._refresh)
        self._ortho.toggled.connect(self._refresh)
        self._snap.toggled.connect(self._on_snap)
        self._grid.valueChanged.connect(self._refresh)

        self._refresh()

    # -- helpers -----------------------------------------------

    def _connect_label(self):
        if self._start_node and self._end_node:
            return "Connect {} -> dots -> {}".format(
                self._start_node.name(), self._end_node.name())
        if self._start_node:
            return "Connect from {}".format(self._start_node.name())
        if self._end_node:
            return "Connect into {}".format(self._end_node.name())
        return "Connect to nodes at the ends"

    def _on_snap(self, checked):
        self._grid.setEnabled(checked)
        self._refresh()

    def _refresh(self, *_args):
        tolerance = float(self._slider.value())
        grid = self._grid.value() if self._snap.isChecked() else 0
        self.points = simplify_path(self._raw,
                                    tolerance=tolerance,
                                    orthogonal=self._ortho.isChecked(),
                                    grid=grid)
        self._tol_label.setText(str(int(tolerance)))
        self._count.setText("{} dots".format(len(self.points)))

        if self._overlay:
            self._overlay.set_path(
                [self._xform.dag_to_local(x, y) for x, y in self.points])

    # -- results -----------------------------------------------

    def connect_ends(self):
        return self._connect.isChecked() and self._connect.isEnabled()

    def save_prefs(self):
        _prefs_save({
            "tolerance": int(self._slider.value()),
            "ortho":     bool(self._ortho.isChecked()),
            "snap":      bool(self._snap.isChecked()),
            "grid":      int(self._grid.value()),
            "connect":   bool(self._connect.isChecked()),
        })


# -- Dot creation ----------------------------------------------

def create_dot_chain(points, start_node=None, end_node=None):
    """
    Build a chain of connected Dots through points, given in DAG
    coordinates as the centre each Dot should sit on.

    The whole chain is one undo step.
    """
    if len(points) < MIN_POINTS:
        _log("only {} point(s) - nothing to create".format(len(points)))
        return []

    undo = nuke.Undo()
    undo.begin(UNDO_NAME)
    try:
        # A new node auto-connects to the selection, which would wire the
        # first Dot somewhere we did not ask for.
        for node in nuke.selectedNodes():
            node.setSelected(False)

        dots = []
        previous = start_node
        for x, y in points:
            dot = nuke.nodes.Dot(inputs=[previous] if previous else [])
            w = dot.screenWidth() or DOT_SIZE
            h = dot.screenHeight() or DOT_SIZE
            dot.setXYpos(int(round(x - w / 2.0)), int(round(y - h / 2.0)))
            previous = dot
            dots.append(dot)

        if end_node is not None and dots:
            try:
                end_node.setInput(0, dots[-1])
            except Exception:
                _log("could not wire {} - {}".format(
                    end_node.name(), traceback.format_exc()))

        for dot in dots:
            dot.setSelected(True)

        _log("created {} dots".format(len(dots)))
        return dots
    finally:
        undo.end()


# -- Event filter ----------------------------------------------

class _Filter(QtCore.QObject):
    """
    Application-wide filter driving idle -> armed -> drawing.

    Armed and drawing swallow their events so a stroke never leaks into the
    DAG's own marquee-select.
    """

    def __init__(self):
        super(_Filter, self).__init__()
        self._mode = "idle"        # idle | armed | drawing
        self._xform = None         # _DagTransform, frozen at mouse-down
        self._points = []          # Stroke samples, in DAG-widget local px
        self._overlay = None
        self._cursor_timer = None

    # -- cursor ------------------------------------------------

    def _start_cursor(self):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CrossCursor)
        self._cursor_timer = QtCore.QTimer()
        self._cursor_timer.timeout.connect(self._enforce_cursor)
        self._cursor_timer.start(50)

    def _enforce_cursor(self):
        QtWidgets.QApplication.changeOverrideCursor(QtCore.Qt.CrossCursor)

    def _stop_cursor(self):
        if self._cursor_timer:
            self._cursor_timer.stop()
            self._cursor_timer.deleteLater()
            self._cursor_timer = None
        while QtWidgets.QApplication.overrideCursor() is not None:
            QtWidgets.QApplication.restoreOverrideCursor()

    # -- state -------------------------------------------------

    def arm(self):
        """Enter draw mode. The next left-drag in the DAG becomes a path."""
        if self._mode != "idle":
            return
        self._mode = "armed"
        self._start_cursor()
        _log("armed")

    def _drop_overlay(self):
        if self._overlay:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None

    def _disarm(self):
        self._mode = "idle"
        self._xform = None
        self._points = []
        self._stop_cursor()
        self._drop_overlay()
        _log("disarmed")

    # -- filter ------------------------------------------------

    def eventFilter(self, obj, event):
        try:
            return self._handle(obj, event)
        except Exception:
            # Always printed, never gated on DEBUG. Landing here means the
            # event is handed back to Nuke, which starts its own selection
            # marquee - the exact symptom of "the tool does nothing". A
            # silent except here hides its own cause.
            print("[DD] EXCEPTION in eventFilter - the click was passed "
                  "back to Nuke:\n{}".format(traceback.format_exc()))
            self._disarm()
            return False

    def _handle(self, obj, event):
        t = event.type()

        # -- IDLE ----------------------------------------------
        if self._mode == "idle":
            if t == QtCore.QEvent.KeyPress:
                if event.key() == SHORTCUT_KEY and \
                        (event.modifiers() & REQUIRE_MODIFIER):
                    # Either source is good enough. Focus is the reliable
                    # one, but a DAG that has been hovered rather than
                    # clicked may not hold it, and refusing to arm then
                    # leaves the drag to Nuke's own selection marquee.
                    focus = QtWidgets.QApplication.focusWidget()
                    under = QtWidgets.QApplication.widgetAt(
                        QtGui.QCursor.pos())
                    if (focus is not None and _is_dag_widget(focus)) or \
                            (under is not None and _is_dag_widget(under)):
                        self.arm()
                        return True
                    _log("shortcut ignored - focus={} under cursor={}".format(
                        _describe(focus), _describe(under)))
            return False

        # -- ARMED ---------------------------------------------
        if self._mode == "armed":
            if t == QtCore.QEvent.KeyPress:
                if event.key() == QtCore.Qt.Key_Escape:
                    self._disarm()
                return True

            if t == QtCore.QEvent.MouseButtonPress:
                if event.button() == QtCore.Qt.LeftButton:
                    return self._begin_stroke(_global_pos(event))
                if event.button() == QtCore.Qt.RightButton:
                    self._disarm()
                    return True
            return False

        # -- DRAWING -------------------------------------------
        if self._mode == "drawing":
            if t == QtCore.QEvent.KeyPress:
                if event.key() == QtCore.Qt.Key_Escape:
                    self._disarm()
                return True

            if t == QtCore.QEvent.MouseButtonPress:
                if event.button() == QtCore.Qt.RightButton:
                    self._disarm()
                return True

            if t == QtCore.QEvent.MouseMove:
                self._sample(_global_pos(event))
                return True

            if t == QtCore.QEvent.MouseButtonRelease:
                if event.button() == QtCore.Qt.LeftButton:
                    self._sample(_global_pos(event), force=True)
                    self._end_stroke()
                return True
            return False

        return False

    # -- stroke ------------------------------------------------

    def _begin_stroke(self, global_point):
        rect = _resolve_dag_rect(global_point)
        if rect is None:
            # Armed, but we cannot tell which widget to measure against.
            # Swallow the click anyway: the user asked for the draw tool,
            # and letting it through instead starts the Node Graph's own
            # selection marquee, which looks like the tool misfiring.
            _log("could not resolve a Node Graph widget - stroke abandoned")
            self._disarm()
            return True

        self._xform = _DagTransform(rect)
        self._points = [self._xform.global_to_local(global_point)]

        # Built after the rect was captured, so the widget lookups above
        # found the DAG and not the overlay itself.
        self._overlay = _PathOverlay(self._xform.zoom)
        self._overlay.setGeometry(self._xform.global_rect())
        self._overlay.show()

        self._mode = "drawing"
        _log("drawing from local {}".format(self._points[0]))
        return True

    def _sample(self, global_point, force=False):
        if self._xform is None:
            return
        point = self._xform.global_to_local(global_point)
        if not force and self._points:
            lx, ly = self._points[-1]
            if math.hypot(point[0] - lx, point[1] - ly) < MIN_SAMPLE_PX:
                return
        self._points.append(point)
        if self._overlay:
            self._overlay.set_raw(self._points)

    def _end_stroke(self):
        transform = self._xform
        overlay = self._overlay
        raw_local = list(self._points)

        # Hand the overlay to the dialog, and stop swallowing events so the
        # panel is usable. The overlay is torn down once the panel closes.
        self._mode = "idle"
        self._overlay = None
        self._xform = None
        self._points = []
        self._stop_cursor()

        raw_dag = [transform.local_to_dag(x, y) for x, y in raw_local]
        _log("stroke finished: {} samples".format(len(raw_dag)))

        if len(_dedupe(raw_dag, 0.5)) < MIN_POINTS:
            _log("stroke too short - nothing created")
            if overlay:
                overlay.hide()
                overlay.deleteLater()
            return

        # Deferred to the next turn of the event loop. The panel is modal,
        # so showing it here would start a nested event loop part-way
        # through delivering this mouse release.
        QtCore.QTimer.singleShot(
            0, lambda: self._prompt(raw_dag, transform, overlay))

    def _prompt(self, raw_dag, transform, overlay):
        """
        Offer the simplify panel, then commit the path if accepted.

        This runs outside eventFilter's own try/except, so it carries its
        own. The overlay is frameless, mouse-transparent and always on top:
        leaking one would strand a ghost stroke over the UI that cannot be
        clicked away.
        """
        try:
            start_node = end_node = None
            if CONNECT_ENDS:
                start_node = _node_near(raw_dag[0][0], raw_dag[0][1],
                                        CONNECT_RADIUS)
                end_node = _node_near(raw_dag[-1][0], raw_dag[-1][1],
                                      CONNECT_RADIUS, need_input=True)
                if end_node is not None and end_node is start_node:
                    end_node = None

            dialog = _SimplifyDialog(raw_dag, transform, overlay,
                                     start_node, end_node)
            dialog.move(int(transform.gx) + 24,
                        int(transform.gy + transform.h) - 190)

            accepted = _exec(dialog) == QtWidgets.QDialog.Accepted
            points = list(dialog.points)
            connect = dialog.connect_ends()
            dialog.save_prefs()

            if not accepted:
                _log("cancelled")
                return

            create_dot_chain(points,
                             start_node if connect else None,
                             end_node if connect else None)
        except Exception:
            _log("exception while committing the path:\n{}".format(
                traceback.format_exc()))
        finally:
            # The panel is modal, so this runs the moment it closes.
            if overlay:
                overlay.hide()
                overlay.deleteLater()


# -- Entry points ----------------------------------------------

_filter = None


# -- Diagnostics -----------------------------------------------
#
# When the tool does not arm, the cause is almost always one of two
# things: the Node Graph is not being recognised, or the shortcut key
# never reaches the event filter. These two functions tell those apart
# without needing a debugger, and their output is meant to be pasted
# into a bug report.

def diagnose():
    """
    Report what this tool can see: versions, filter state, and every
    widget that looks like a Node Graph.

    Safe to run from the Script Editor - it does not need the Node Graph
    to have focus, because it searches every widget in the application.
    """
    out = ["", "=" * 62, "NukeDrawDots {} diagnostics".format(__version__),
           "=" * 62]

    try:
        out.append("Nuke        {}".format(nuke.NUKE_VERSION_STRING))
    except Exception:
        out.append("Nuke        (version unavailable)")
    out.append("Python      {}.{}.{}".format(*sys.version_info[:3]))
    out.append("Binding     PySide{}, Qt {}".format(
        _PYSIDE_MAJOR, QtCore.qVersion()))
    out.append("Filter      {}".format(
        "installed, mode={}".format(_filter._mode) if _filter
        else "NOT INSTALLED - run nuke_draw_dots.install()"))
    out.append("Shortcut    {} + key {}".format(
        "Shift" if REQUIRE_MODIFIER == QtCore.Qt.ShiftModifier
        else str(REQUIRE_MODIFIER),
        QtGui.QKeySequence(SHORTCUT_KEY).toString() or SHORTCUT_KEY))

    app = QtWidgets.QApplication.instance()
    if app is None:
        out.append("")
        out.append("No QApplication - nothing further to report.")
        print("\n".join(out))
        return

    try:
        widgets = app.allWidgets()
    except Exception:
        widgets = []

    # Distinct widgets the matcher accepts, deduped by identity.
    accepted = []
    seen = set()
    dead = 0
    for w in widgets:
        try:
            if not _widget_is_live(w):
                dead += 1
                continue
            if not w.isVisible():
                continue
            reason = _dag_match(w)
            if reason is None:
                continue
            key = (w.metaObject().className(), w.objectName(),
                   w.width(), w.height())
        except RuntimeError:
            dead += 1
            continue
        if key in seen:
            continue
        seen.add(key)
        accepted.append((w, reason))

    out.append("")
    out.append("Node Graph detection: {} visible widget(s) accepted"
               .format(len(accepted)))
    if dead:
        # Nuke 14.1 keeps wrappers for destroyed QGLWidgets alive and hands
        # them back from widgetAt(); seeing them here is expected, not a
        # fault, as long as the tool skips them.
        out.append("    ({} stale widget wrapper(s) skipped)".format(dead))

    if accepted:
        # Biggest first - the real DAG viewport is the large one.
        accepted.sort(key=lambda pair: pair[0].width() * pair[0].height(),
                      reverse=True)
        for w, reason in accepted[:8]:
            out.append("    {:>5}x{:<5}  {}".format(
                w.width(), w.height(), reason))
        out.append("")
        out.append("Detection looks OK. If the tool still will not arm,")
        out.append("run nuke_draw_dots.key_probe() and press the shortcut.")
    else:
        out.append("    NOTHING MATCHED - this is why the tool will not arm.")
        out.append("")
        out.append("Largest visible widgets, for adding to DAG_TAGS:")
        candidates = []
        for w in widgets:
            try:
                if not w.isVisible() or w.width() < 200 or w.height() < 200:
                    continue
                candidates.append(
                    (w.width() * w.height(), w.metaObject().className(),
                     w.objectName(), w.width(), w.height()))
            except RuntimeError:
                continue
        candidates.sort(reverse=True)
        shown = set()
        for _area, cls, name, width, height in candidates:
            if (cls, name) in shown:
                continue
            shown.add((cls, name))
            out.append("    {:>5}x{:<5}  {}({})".format(
                width, height, cls, name or "-"))
            if len(shown) >= 20:
                break

    out.append("=" * 62)
    print("\n".join(out))


class _KeyProbe(QtCore.QObject):
    """
    Prints the key and mouse events an application-wide filter actually
    receives, then removes itself.

    Mouse events matter as much as keys: if a press never appears here,
    this tool's whole approach cannot work in that Nuke, because an
    app-level filter is how it claims the drag. If a press does appear but
    the tool still does nothing, the fault is in the tool's own handler.
    """

    def __init__(self, seconds):
        super(_KeyProbe, self).__init__()
        self._seconds = seconds
        self._moves = 0

    def eventFilter(self, obj, event):
        try:
            kind = event.type()

            if kind == QtCore.QEvent.MouseMove:
                self._moves += 1
                return False

            if kind in (QtCore.QEvent.MouseButtonPress,
                        QtCore.QEvent.MouseButtonRelease):
                where = QtWidgets.QApplication.widgetAt(_global_pos(event))
                print("[probe] {}  button={}  under={}  dag={}".format(
                    "PRESS  " if kind == QtCore.QEvent.MouseButtonPress
                    else "RELEASE",
                    event.button(),
                    _describe(where),
                    bool(where is not None and _dag_match(where))))
                return False

            if kind == QtCore.QEvent.KeyPress:
                key = event.key()
                mods = event.modifiers()
                focus = QtWidgets.QApplication.focusWidget()
                # No int() on modifiers - PySide6's newer enums refuse the
                # cast, and a diagnostic that dies quietly is worse than
                # useless. Test each flag instead.
                print("[probe] key={} ({})  shift={} ctrl={} alt={}  "
                      "focus={}  dag={}".format(
                          key,
                          QtGui.QKeySequence(key).toString() or "?",
                          bool(mods & QtCore.Qt.ShiftModifier),
                          bool(mods & QtCore.Qt.ControlModifier),
                          bool(mods & QtCore.Qt.AltModifier),
                          _describe(focus),
                          bool(focus is not None and _dag_match(focus))))
        except Exception:
            print("[probe] error:\n{}".format(traceback.format_exc()))
        return False

    def stop(self):
        app = QtWidgets.QApplication.instance()
        if app:
            app.removeEventFilter(self)
        print("[probe] stopped after {}s - saw {} mouse-move events"
              .format(self._seconds, self._moves))
        if not self._moves:
            print("[probe] NO mouse events reached the filter at all. An "
                  "app-level event filter cannot see this Nuke's input, "
                  "which is why the drag falls through to Nuke.")


def key_probe(seconds=15):
    """
    Watch key presses for a few seconds and print each one.

    Run this, then click and drag in the Node Graph and press the
    shortcut. Both keys and mouse buttons are reported.

    No [probe] line for the key  -> something upstream eats it; change
                                    SHORTCUT_KEY.
    No PRESS line when you click -> app-level filters cannot see this
                                    Nuke's mouse input at all.
    PRESS appears but the tool
    still does nothing           -> the fault is in this tool's handler;
                                    look for a [DD] EXCEPTION line.
    """
    app = QtWidgets.QApplication.instance()
    if app is None:
        print("[probe] no QApplication")
        return
    probe = _KeyProbe(seconds)
    app.installEventFilter(probe)
    print("[probe] watching keys and mouse for {}s - click, drag, and "
          "press the shortcut in the Node Graph now".format(seconds))
    QtCore.QTimer.singleShot(int(seconds * 1000), probe.stop)
    return probe


_UNSET = object()   # tells "argument omitted" from "explicitly None"


def set_shortcut(key, modifier=_UNSET):
    """
    Change the arming shortcut for the rest of this Nuke session.

        nuke_draw_dots.set_shortcut("E")            # Shift+E
        nuke_draw_dots.set_shortcut("E", None)      # plain E, no modifier

    key may be a single character or a QtCore.Qt.Key_* constant. Useful for
    finding a key Nuke is not already using without editing the file and
    restarting - once one works, set SHORTCUT_KEY at the top of this module
    to make it stick, and update the hotkey in menu.py to match.
    """
    global SHORTCUT_KEY, REQUIRE_MODIFIER

    if isinstance(key, str):
        if len(key) != 1:
            raise ValueError("pass a single character, not {!r}".format(key))
        name = "Key_" + key.upper()
        if not hasattr(QtCore.Qt, name):
            raise ValueError("no Qt key called {}".format(name))
        key = getattr(QtCore.Qt, name)

    SHORTCUT_KEY = key
    if modifier is not _UNSET:
        REQUIRE_MODIFIER = modifier

    label = QtGui.QKeySequence(SHORTCUT_KEY).toString() or str(SHORTCUT_KEY)
    if REQUIRE_MODIFIER:
        prefix = "Shift+" if REQUIRE_MODIFIER == QtCore.Qt.ShiftModifier \
            else "{}+".format(REQUIRE_MODIFIER)
        label = prefix + label
    print("[DD] shortcut is now {} (this session only)".format(label))
    return label


def arm():
    """Arm the tool from a menu command, without the keyboard shortcut."""
    install()
    if _filter:
        _filter.arm()


def install():
    global _filter
    if _filter:
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        _log("no QApplication - not installing")
        return
    _filter = _Filter()
    app.installEventFilter(_filter)
    _log("installed - Shift+D in the Node Graph to draw")


def uninstall():
    global _filter
    if _filter:
        _filter._disarm()
        app = QtWidgets.QApplication.instance()
        if app:
            app.removeEventFilter(_filter)
        _filter = None
        _log("uninstalled")


if nuke.GUI:
    QtCore.QTimer.singleShot(2000, install)
