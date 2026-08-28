# -*- coding: utf-8 -*-
"""
build_dist.py
-------------
Stage the release payload into dist/ and zip it.

    python tools/build_dist.py

Produces:

    dist/NukeDrawDots-<version>/     committed, browsable on GitHub
        nuke_draw_dots.py
        menu.py                      complete drop-in, not a snippet
        INSTALL.txt
        LICENSE
    dist/NukeDrawDots-<version>.zip  gitignored build artifact

The version is read from src/nuke_draw_dots.py, so bumping __version__ is
the only edit needed to cut a new release.
"""

from __future__ import print_function
import io
import os
import re
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
DIST = os.path.join(ROOT, "dist")

# The line in src/menu.py that frames it as a snippet. In the distributed
# copy menu.py is a complete file, so this gets swapped for drop-in wording.
SNIPPET_HEADER = "# menu.py - add these lines to your existing ~/.nuke/menu.py"
DROPIN_HEADER = "# menu.py - Nuke reads this from ~/.nuke/ at startup"


def read(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def get_version():
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']',
                  read(os.path.join(SRC, "nuke_draw_dots.py")), re.M)
    if not m:
        sys.exit("could not find __version__ in src/nuke_draw_dots.py")
    return m.group(1)


def build_menu():
    """src/menu.py is written as a snippet; distribute it as a whole file."""
    text = read(os.path.join(SRC, "menu.py"))
    if SNIPPET_HEADER not in text:
        sys.exit("src/menu.py header changed - update SNIPPET_HEADER here")
    return text.replace(SNIPPET_HEADER, DROPIN_HEADER, 1)


INSTALL = u"""NukeDrawDots {version}
==========================

Draw a freehand path in the Node Graph and turn it into a chain of
connected Dot nodes. Nuke 14.1 through 17.1, MIT licensed.

Verified in live Nuke 14.1v8 and 17.1v1 sessions - one per Qt binding.

https://github.com/bratgot/NukeDrawDots


INSTALL
-------
1. Copy nuke_draw_dots.py into your ~/.nuke/ folder.

   Windows:  %USERPROFILE%\\.nuke\\
   Linux:    ~/.nuke/
   macOS:    ~/.nuke/

2. Copy menu.py into the same folder.

   IMPORTANT: if you ALREADY have a ~/.nuke/menu.py, do not overwrite it.
   Open both files and append the contents of this menu.py to the end of
   your existing one instead.

3. Restart Nuke.

To load without restarting, run this in the Script Editor:

    import nuke_draw_dots
    nuke_draw_dots.install()


USE
---
  Shift+D         Arm the tool (cursor becomes a crosshair)
  Click + drag    Draw the path
  Release         The Dots appear
  Escape          Cancel at any point
  Right-click     Cancel at any point

Nodes toolbar -> Other -> Draw Dots
    Arms the tool without the keyboard shortcut.

Nodes toolbar -> Other -> Draw Dots Settings...
    Simplify strength, right angles, grid snap and connecting. Set once
    and remembered between sessions - a stroke goes straight to Dots
    without stopping to ask. Turn on "Show this panel after every stroke"
    if you would rather confirm each path against a live preview.

    The panel is not modal: leave it open beside the Node Graph and keep
    drawing. There is no OK button - every change is saved as you make it
    and applies to the next stroke.


SETTINGS
--------
By default a stroke becomes Dots straight away, using whatever is set in
Draw Dots Settings. Turn on "Show this panel after every stroke" there and
the panel below opens on each release instead.

Everything in the panel previews live over the Node Graph. The faint grey
line is the stroke you drew; the orange line and circles are the Dots you
are about to get.

  Simplify        How far the path may stray from your stroke, in Node
                  Graph units. 0 keeps every sample. Drag it up until the
                  dot count looks right.

  Right angles    Snap every segment to horizontal or vertical, so the
                  chain routes like a circuit board rather than following
                  your hand. On by default.

  Snap to grid    Round every Dot to a multiple of the grid size, so the
                  chain lines up with nodes you placed by hand.

  Connect ...     If the stroke started on a node, the first Dot is wired
                  to it. If it ended on a node, the chain goes into that
                  node's first FREE input - an existing connection is
                  never overwritten, and a Merge's mask is skipped.

                  End the stroke on a pipe instead and the chain is
                  spliced into it: upstream -> dots -> downstream.

                  No Dot is placed on a node you connect to; drawing onto
                  it is the connect gesture. The checkbox names whatever
                  was found and is greyed out when neither end landed on
                  anything.

Create commits the chain as a single undo step, so one Ctrl+Z removes all
of it. The new Dots are left selected.

Panel settings are remembered between Nuke sessions in
~/.nuke/nuke_draw_dots_prefs.json - delete that file to reset.


TROUBLESHOOTING
--------------
Two diagnostics are built in. Run them in the Script Editor of the Nuke
that is misbehaving:

    import nuke_draw_dots
    nuke_draw_dots.diagnose()

Prints the Nuke, Python and Qt versions, whether the event filter is
installed, and every widget it recognises as a Node Graph. It searches
the whole application, so the Node Graph does not need focus. If it says
NOTHING MATCHED, it then lists the largest visible widgets - that list is
what to report.

    nuke_draw_dots.key_probe()

Watches keys and mouse buttons for 15 seconds. Click, drag and press the
shortcut in the Node Graph. No line for the key means something else has
claimed it; no PRESS line when you click means an application-level event
filter cannot see this Nuke's input at all.

To try a different key without editing the file or restarting:

    nuke_draw_dots.set_shortcut("E")     # Shift+E for this session

Once one works, set SHORTCUT_KEY at the top of nuke_draw_dots.py and the
hotkey in menu.py to match.

For anything else, set DEBUG = True and watch for [DD] lines.


NOTES
-----
No third-party packages are needed. The Qt binding is detected at import:
PySide6 on Nuke 16+, PySide2 on 14-15.

The "shift+d" hotkey on the toolbar command is a fallback. While the Node
Graph has focus the event filter claims Shift+D first, so the key and the
menu command do the same thing.


CONFIGURATION
-------------
At the top of nuke_draw_dots.py:

  SHORTCUT_KEY      = QtCore.Qt.Key_D   the key that arms the tool
  REQUIRE_MODIFIER  = ShiftModifier     the modifier it needs
  MIN_SAMPLE_PX     = 3                 screen px between stroke samples
  DEFAULT_TOLERANCE = 12                starting Simplify amount
  DEFAULT_ORTHO     = True              start with right angles on
  DEFAULT_SNAP      = False             start with grid snapping off
  DEFAULT_GRID      = 16                starting grid size
  CONNECT_ENDS      = True              look for nodes under the ends
  CONNECT_RADIUS    = 45                how near an end has to be
  PIPE_RADIUS       = 30                how near an end has to be to a pipe
  TRIM_PADDING      = 30                clearance kept around a connected node
  STRAIGHT_TOL      = 12                how far off-line a Dot must be to keep
  DEBUG             = False             print [DD] trace lines

The DEFAULT_ values seed the panel the first time only; after that the
prefs file wins.


LICENSE
-------
MIT - see LICENSE.
"""


def main():
    version = get_version()
    name = "NukeDrawDots-{}".format(version)
    stage = os.path.join(DIST, name)

    if not os.path.isdir(DIST):
        os.makedirs(DIST)
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)

    # dist/ mirrors the current version only. Older payloads stay available
    # on their GitHub release pages, so keeping them here just accumulates
    # stale copies the README no longer links to.
    for entry in sorted(os.listdir(DIST)):
        if not entry.startswith("NukeDrawDots-") or entry == name:
            continue
        if entry == name + ".zip":
            continue
        stale = os.path.join(DIST, entry)
        if os.path.isdir(stale):
            shutil.rmtree(stale)
        else:
            os.remove(stale)
        print("removed stale {}".format(stale))

    shutil.copyfile(os.path.join(SRC, "nuke_draw_dots.py"),
                    os.path.join(stage, "nuke_draw_dots.py"))
    write(os.path.join(stage, "menu.py"), build_menu())
    write(os.path.join(stage, "INSTALL.txt"), INSTALL.format(version=version))
    shutil.copyfile(os.path.join(ROOT, "LICENSE"),
                    os.path.join(stage, "LICENSE"))

    zip_path = os.path.join(DIST, name + ".zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(os.listdir(stage)):
            zf.write(os.path.join(stage, entry), os.path.join(name, entry))

    # Verify what we just wrote actually reads back.
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad is not None:
            sys.exit("corrupt entry in zip: {}".format(bad))
        names = sorted(zf.namelist())

    print("built {}".format(stage))
    for entry in sorted(os.listdir(stage)):
        size = os.path.getsize(os.path.join(stage, entry))
        print("    {:<22} {:>7,} bytes".format(entry, size))
    print("built {}  ({:,} bytes)".format(zip_path,
                                          os.path.getsize(zip_path)))
    for n in names:
        print("    {}".format(n))


if __name__ == "__main__":
    main()
