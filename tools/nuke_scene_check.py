# -*- coding: utf-8 -*-
"""
nuke_scene_check.py
-------------------
Paste this into Nuke's Script Editor and run it.

It reloads the tool, builds a small test graph off to one side of whatever
you already have open, and then asks the tool directly what it would do if
a stroke ended on each pipe. That answers "does splicing work?" without
depending on how accurately you can draw with a mouse.

Nothing existing is deleted. The test nodes are all named DD_*, so
    for n in nuke.allNodes():
        if n.name().startswith("DD_"):
            nuke.delete(n)
clears them again.
"""

import sys
import importlib
import nuke

SRC = r"C:\dev\NukeDrawDots\src"     # edit if you moved the repo

# -- reload the tool -------------------------------------------

if SRC not in sys.path:
    sys.path.insert(0, SRC)

import nuke_draw_dots                                   # noqa: E402
try:
    nuke_draw_dots.uninstall()      # drop the old event filter first
except Exception:
    pass
importlib.reload(nuke_draw_dots)
dd = nuke_draw_dots
dd.DEBUG = True
dd.install()

print("=" * 62)
print("NukeDrawDots {}  loaded from {}".format(dd.__version__, dd.__file__))
print("=" * 62)


# -- build the test graph --------------------------------------

def clear_test_nodes():
    for node in nuke.allNodes():
        if node.name().startswith("DD_"):
            nuke.delete(node)


clear_test_nodes()

# Put the test well clear of anything already in the script.
base_x, base_y = 0, 0
others = [n for n in nuke.allNodes() if not n.name().startswith("DD_")]
if others:
    base_y = max(n.ypos() for n in others) + 400

for node in nuke.selectedNodes():
    node.setSelected(False)

# A: a long pipe, easy to draw onto.
a_src = nuke.nodes.Constant(name="DD_A_src")
a_src.setXYpos(base_x, base_y)
a_dst = nuke.nodes.Blur(name="DD_A_dst", inputs=[a_src])
a_dst.setXYpos(base_x, base_y + 600)

# B: a short pipe - the case that used to be unspliceable, because both
# nodes sit within CONNECT_RADIUS of every point on the pipe.
b_src = nuke.nodes.Constant(name="DD_B_src")
b_src.setXYpos(base_x + 400, base_y)
b_dst = nuke.nodes.Merge2(name="DD_B_dst", inputs=[b_src])
b_dst.setXYpos(base_x + 400, base_y + 120)

for node in nuke.selectedNodes():
    node.setSelected(False)

# Bring the test graph into view. It is placed clear of your existing
# nodes, which usually puts it outside the current view - and drawing on
# empty space quite correctly connects to nothing.
view_x = base_x + 200
view_y = base_y + 350
nuke.zoom(1.0, [view_x, view_y])

_centre = nuke.center()
_zoom = nuke.zoom()
print("")
print("Node Graph view: centre ({:.0f}, {:.0f})  zoom {:.2f}".format(
    _centre[0], _centre[1], _zoom))
if abs(_centre[0] - view_x) > 50 or abs(_centre[1] - view_y) > 50:
    print("WARNING: the view did not move to the test graph.")
    print("         Scroll to the DD_* nodes by hand before drawing,")
    print("         or the stroke will land on empty space.")


# -- helpers you can call after drawing ------------------------

# Everything present now. Any Dot appearing later was made by the tool
# during this test, so dd_cleanup() can take it away again.
_before = set(n.name() for n in nuke.allNodes())


def dd_show():
    """Print how the test graph is actually wired, right now."""
    print("")
    print("-- actual wiring ".ljust(62, "-"))
    for downstream in (a_dst, b_dst):
        chain = [downstream.name()]
        node = downstream.input(0)
        for _ in range(30):
            if node is None:
                chain.append("(nothing)")
                break
            chain.append(node.name())
            node = node.input(0)
        print("   " + "  <-  ".join(chain))

    loose = []
    for n in nuke.allNodes():
        if n.Class() != "Dot" or n.name() in _before:
            continue
        try:
            if not n.dependent():
                loose.append(n)
        except Exception:
            pass
    if loose:
        print("   Dots with nothing downstream: {}".format(
            ", ".join(n.name() for n in loose)))
    print("")
    print("   Read right to left: source on the right, DD_*_dst on the")
    print("   left. A finished splice reads dst <- Dot.. <- .. <- src.")


def dd_cleanup():
    """Remove the test nodes and any Dots this test created."""
    removed = 0
    for node in nuke.allNodes():
        if node.name().startswith("DD_") or (
                node.Class() == "Dot" and node.name() not in _before):
            nuke.delete(node)
            removed += 1
    print("removed {} test node(s)".format(removed))


# -- ask the tool what it would do -----------------------------

def midpoint(upstream, downstream):
    ax, ay = dd._node_centre(upstream)
    bx, by = dd._node_centre(downstream)
    return ((ax + bx) / 2.0, (ay + by) / 2.0)


def report(title, upstream, downstream):
    px, py = midpoint(upstream, downstream)
    print("")
    print("-- {} ".format(title).ljust(62, "-"))
    print("   pipe {} -> {},  midpoint ({:.0f}, {:.0f})".format(
        upstream.name(), downstream.name(), px, py))

    pipe = dd._pipe_near(px, py)
    if pipe is None:
        print("   _pipe_near      : NOTHING FOUND  <-- detection failed")
    else:
        up, down, index = pipe
        print("   _pipe_near      : {} -> {} ({})".format(
            up.name(), down.name(), dd._input_label(down, index)))

    # A stroke of a few samples ending on the pipe, as if drawn there.
    stroke = [(px - 20, py - 20), (px - 10, py - 10), (px, py)]
    start, end, index, inserting = dd._resolve_connections(stroke)
    print("   would splice     : {}".format("YES" if inserting else "NO"))
    print("   start node       : {}".format(start.name() if start else None))
    print("   end node / input : {} / {}".format(
        end.name() if end else None,
        dd._input_label(end, index) if end else None))
    return inserting


long_ok = report("A: long pipe", a_src, a_dst)
short_ok = report("B: short pipe", b_src, b_dst)

print("")
print("=" * 62)
if long_ok and short_ok:
    print("Splice detection works on both pipes.")
    print("")
    print("The view has been moved to the test graph, so the pipes are")
    print("on screen now. Press Shift+D and drag a short stroke ALONG one")
    print("of the two vertical pipes. The panel's checkbox should read")
    print("\"Insert into DD_..._src -> dots -> DD_..._dst\".")
    print("Watch for a [DD] splicing into ... line as you release.")
    print("")
    print("THEN run  dd_show()  to print how the graph is really wired.")
    print("That is the ground truth - the [DD] lines only say what the")
    print("tool attempted. dd_cleanup() removes the test nodes and any")
    print("Dots left over from earlier attempts.")
else:
    print("Splice detection FAILED above - copy this whole block back.")
    print("The [DD] connections: line says what each stage resolved to.")
print("=" * 62)
