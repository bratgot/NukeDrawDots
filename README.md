# NukeDrawDots

A Nuke tool that lets you **draw a path in the Node Graph** and turn it into a chain of connected Dot nodes — instead of placing dots one at a time and dragging each into line.

![Nuke Version](https://img.shields.io/badge/Nuke-14.1%20–%2017.1-lightgrey) ![PySide](https://img.shields.io/badge/PySide-2%20%7C%206-blue) ![License](https://img.shields.io/badge/License-MIT-green)

---

## Features

- **Draw to route** — press `Shift+D`, drag a freehand path, release
- **Simplify** — a slider trades detail for dot count, previewed live over the DAG
- **Right angles** — snap every segment to horizontal or vertical, so the chain routes like a circuit board rather than following your hand
- **Grid snap** — round every dot to a grid so the chain lines up with nodes you placed by hand
- **Auto-connect** — start the stroke on a node and the first dot wires to it; end on a node and that node's first input wires to the last dot
- **One undo** — the whole chain goes in and comes out with a single `Ctrl+Z`
- **Cross-version** — Nuke 14.1 through 17.1 (PySide2 and PySide6, auto-detected)
- **No dependencies** — one file, standard library and the bundled Qt only

---

## Requirements

| Nuke | Qt binding |
|------|-----------|
| 14.1 – 15.x | PySide2 (bundled) |
| 16 – 17.1 | PySide6 (bundled) |

No third-party packages required.

> **Testing status.** Drawing, the panel and dot creation are **confirmed working in live Nuke 14.1v8 and 17.1v1 sessions** — one per Qt binding, the two ends of the supported range.
>
> The three suites in `tools/` (see [Development](#development)) cover the rest headlessly. `test_static.py` imports the module against each installed Nuke's own bundled Qt and resolves every Qt symbol the module names — it passes on **14.1v8, 15.2v9, 16.0v8, 16.1v1, 17.0v4 and 17.1v1**, across both PySide2 (Qt 5.15.2) and PySide6 (Qt 6.5.3), on Python 3.9 through 3.11.
>
> 15.x and 16.x have not been driven through a live GUI, but they share a binding with a version that has. If something misbehaves, `diagnose()` and `key_probe()` are built in — see [Troubleshooting](#troubleshooting).

---

## Installation

Copy the two files from [`dist/NukeDrawDots-1.1.0/`](dist/NukeDrawDots-1.1.0) into `~/.nuke/` and restart Nuke.

> If you already have a `~/.nuke/menu.py`, don't overwrite it — append the distributed `menu.py` to the end of yours instead.

To wire it up by hand:

1. Copy `nuke_draw_dots.py` into `~/.nuke/`
2. Add the following to `~/.nuke/menu.py`:

```python
# menu.py — add these lines to your existing ~/.nuke/menu.py
# ─────────────────────────────────────────────────────────────
# Compatible with Nuke 14.1–15.x (PySide2) and 16+ (PySide6)

import nuke_draw_dots

toolbar = nuke.toolbar("Nodes")

toolbar.addCommand(
    "Other/Draw Dots",
    "nuke_draw_dots.arm()",
    "shift+d",
    icon="Dot.png",
)
```

Restart Nuke, or run `nuke_draw_dots.install()` from the Script Editor to load without restarting.

---

## Usage

1. Click in the Node Graph so it has focus
2. Press **`Shift+D`** — the cursor becomes a crosshair
3. **Click and drag** to draw the path you want the dots to follow
4. Release — the dots appear

> Press `Escape` or right-click at any point to cancel.

By default there's nothing to confirm: the stroke becomes dots using your saved settings. Change those in **Nodes toolbar → Other → Draw Dots Settings…**

### Settings

| Control | What it does |
|---------|--------------|
| **Simplify** | How far the path may stray from your stroke, in Node Graph units. `0` keeps every sample of the drag. |
| **Right angles** | Snap every segment to horizontal or vertical. On by default. |
| **Snap to grid** | Round every dot to a multiple of the grid size. Off by default. |
| **Connect to nodes and pipes** | Wire the chain into whatever the stroke starts and ends on. |
| **Show this panel after every stroke** | Off by default. Turn it on to confirm each path against a live preview before committing. |

The panel is **non-modal**, so you can leave it open beside the Node Graph and keep drawing. There's no OK button — every change is written the moment you make it and applies to the next stroke. Settings live in `~/.nuke/nuke_draw_dots_prefs.json` and are restored next time Nuke starts; delete that file to reset.

### Confirming each stroke

With **Show this panel after every stroke** turned on, releasing the drag opens the panel instead of committing straight away. The faint grey line is the stroke you drew; the orange line and circles are the dots you're about to get, redrawn as you move the controls. It carries the same controls plus a live dot count, and **Create** commits.

### The panel

| Control | What it does |
|---------|--------------|
| **Simplify** | How far the path may stray from your stroke, in Node Graph units. `0` keeps every sample of the drag. Drag it up until the dot count looks right. |
| **Right angles** | Snap every segment to horizontal or vertical. On by default. |
| **Snap to grid** | Round every dot to a multiple of the grid size. Off by default. |
| **Connect …** | Wire the chain into the nodes found under the ends of the stroke. The label names them; the checkbox is greyed out when neither end landed on anything. |

Create commits the chain as a single undo step and leaves the new dots selected.

### Connecting to existing nodes

Both ends are geometric, not selection-based — you connect by *where you draw*, not by what you selected first:

- Start the stroke **on a node** → the first dot takes that node's output.
- End the stroke **on a node** → that node's input 0 is rewired to the last dot.

An end has to land within `CONNECT_RADIUS` (45 Node Graph units) of a node's box. Backdrops and sticky notes are ignored, so a stroke drawn across a backdrop still finds the nodes inside it.

**Dots mark corners, nothing else.** Draw straight from one node to another and you get no dots at all — just the connection. The two node centres act as the route's real endpoints, so a dot that doesn't bend the path away from the line between them is redundant and is dropped (`STRAIGHT_TOL`, 12 Node Graph units, which also absorbs hand wobble). A route that genuinely turns keeps a dot at every corner.

**No dot is placed on or near a node you're connecting to.** Drawing onto a node is how you say "connect here" — a Dot sitting on it, or parked against its edge, is clutter rather than routing. Points falling within `TRIM_PADDING` (30 Node Graph units) of either end node are dropped. The margin is measured from the node's box, and is wide enough that a dot never appears to touch the node while still leaving room for one in the gap between two stacked nodes. Only the ends are trimmed; a stroke deliberately routed over a node in the middle keeps its dots. The preview shows the trimmed result, so what you see is what gets built.

**Draw onto a pipe to splice into it.** Start *or* end the stroke on an existing connection and the chain is inserted into it — upstream → dots → downstream — taking over that pipe, the way dropping a node on a connection works in Nuke. If the stroke *also* started on a node, that node is kept as the source instead of the pipe's upstream: you drew from it deliberately. The tool refuses to splice a node into the pipe that feeds it, which would make a loop.

The dot that lands **on the line** is the one spliced in: the connection runs `upstream → that dot → downstream`. Every dot drawn after it hangs off it as a branch, and **the far end is left free** for you to wire up by hand. Wiring the last dot instead would make the connection detour out to wherever your stroke finished and come back, which is a diversion rather than an insertion.

Either end of the stroke works. Start on a pipe and drag away — "pull a route out of this connection to here" — or end on one. When the pipe is under the stroke's end, the chain is reversed before wiring so the on-line dot still leads it.

What wins where matters, because these tests overlap. Landing squarely **on** a node (`ON_NODE_RADIUS`, 6 units) connects to that node. Otherwise a pipe within `PIPE_RADIUS` (30) is spliced. Only if neither hits does a node merely *near* the end (`CONNECT_RADIUS`, 45) get connected. The order is deliberate: two nodes a short distance apart sit within 45 units of every point on the pipe between them, so letting proximity win would make that pipe impossible to draw onto.

**Free pipes only.** The end node is wired into its first *unconnected* input, not blindly into input 0. Draw into a Merge whose B is already fed and the chain lands in A; the existing link is never overwritten. The mask input is skipped — on a Merge it sits between A and the extra A inputs, and routing an image into it is never what a stroke meant. A node with every pipe taken isn't offered as a target at all, so a connection can't silently break an existing one. The checkbox names the pipe it will use.

---

## How it works

The Node Graph is a Qt widget, and the NDK has no API for it — `DD::Image` operators can't see or draw on the DAG. So this is Python and Qt, not C++: an application-wide `QEventFilter` claims `Shift+D` when the Node Graph either holds focus or is under the cursor, and a frameless translucent top-level widget floats over the graph to paint the preview. That's also why speed isn't a concern — the stroke and the preview never leave Qt, and after simplifying you're creating perhaps five to thirty nodes.

Two details are worth knowing if you're reading the source:

**The screen ⇄ DAG transform is frozen at mouse-down.** Mapping a screen point into DAG coordinates needs the DAG widget's size and position along with `nuke.zoom()` and `nuke.center()`. A freehand stroke wanders outside the widget, where `QApplication.widgetAt()` returns something else entirely, so re-resolving the widget per sample breaks the mapping mid-drag. `_DagTransform` captures all of it once and every sample is mapped through that.

**Order of operations in `simplify_path`.** Dedupe → [RDP](https://en.wikipedia.org/wiki/Ramer%E2%80%93Douglas%E2%80%93Peucker_algorithm) → right angles → grid → drop collinear. Right angles come after RDP so the staircase is built from corners you actually drew rather than from mouse jitter. The grid comes last because snapping a horizontal segment moves both of its ends to the same row, so the right angles survive it — the other order does not hold.

RDP is iterative rather than recursive. A long stroke is easily a few thousand samples, and the textbook recursive form runs out of stack on those.

**No widget reference outlives a call into Nuke.** This one cost real debugging. Nuke 14.1 destroys the Node Graph's `QGLWidget` during ordinary work and `QApplication.widgetAt()` hands back wrappers for objects that are already gone. Such a wrapper still answers `metaObject()` — so a class-name test calls it a Node Graph — and raises `RuntimeError` on `width()`. Worse, checking it is alive is not enough: calling `nuke.zoom()` is itself sufficient to destroy it, so a widget validated one line earlier can be dead by the next. `_capture_dag_rect()` therefore snapshots the geometry to plain numbers before anything else happens, `_search_dag_widgets()` returns every candidate so a dead one can be stepped over, and `_DagTransform` takes a tuple rather than a widget. Nuke 16+ never exhibits this, which is why the tool worked on 17.1 long before it worked on 14.1.

---

## Troubleshooting

**It doesn't work — start here.** Two functions answer almost every case. Run them in the Script Editor of the Nuke that's misbehaving and read the output:

```python
import nuke_draw_dots
nuke_draw_dots.diagnose()
```

`diagnose()` prints the Nuke/Python/Qt versions, whether the event filter is installed, and **every visible widget it recognises as a Node Graph**. It searches the whole application, so the Node Graph does not need focus.

- If it lists one or more accepted widgets, detection is fine — move on to `key_probe()`.
- If it says `NOTHING MATCHED`, that is the bug: this Nuke names its Node Graph widgets differently. It then prints the largest visible widgets with their class and object names. Send that list and the fix is adding a string to `DAG_TAGS`.

```python
nuke_draw_dots.key_probe()      # watches keys for 15 seconds
```

Then click in the Node Graph and press `Shift+D`. Each key press prints a `[probe]` line with the key, the modifiers, the focused widget, and whether that widget counts as a Node Graph.

- **No `[probe]` line for `Shift+D`** → something upstream is eating the key before any event filter sees it. Change `SHORTCUT_KEY`.
- **A line with `dag=False`** → the key arrives but the focused widget isn't recognised; same fix as `NOTHING MATCHED` above.
- **A line with `dag=True`, yet nothing happens** → the key and detection are both fine, and the problem is later. Set `DEBUG = True` and read the `[DD]` trace.

**Nuke's selection marquee appears when I drag.** That is the Node Graph's own rubber-band select, and it means the click reached Nuke instead of this tool — so the tool was either never armed, or armed and then stood down before the press.

Turn the trace on and watch the Script Editor while you repeat it:

```python
import nuke_draw_dots
nuke_draw_dots.DEBUG = True
```

Then press `Shift+D` and drag. What you see tells you which half failed:

| Trace | Meaning |
|---|---|
| `armed` then `drawing from local …` | The tool has the drag; the marquee is coming from somewhere else. |
| `shortcut ignored - focus=… under cursor=…` | `Shift+D` never armed. Neither named widget was recognised as a Node Graph — send me those two names. |
| `could not resolve a Node Graph widget` | Armed, but the click could not be tied to a DAG. The click is swallowed rather than passed on, so you should *not* see a marquee in this case. |
| nothing at all | The event filter isn't installed. Run `nuke_draw_dots.install()`. |

If the trace shows nothing when you press `Shift+D`, something upstream is eating the key — check whether another tool or a Nuke shortcut has claimed `Shift+D`, and change `SHORTCUT_KEY` if so.

**A ghost stroke is stuck on screen.** Run `nuke_draw_dots.uninstall()` in the Script Editor, then `install()` again.

---

## Configuration

At the top of `nuke_draw_dots.py`:

```python
SHORTCUT_KEY      = QtCore.Qt.Key_D   # The key that arms the tool
REQUIRE_MODIFIER  = QtCore.Qt.ShiftModifier

MIN_SAMPLE_PX     = 3     # Screen px a stroke must travel before resampling
DEFAULT_TOLERANCE = 12    # Starting Simplify amount, in DAG units
DEFAULT_ORTHO     = True  # Start with right angles on
DEFAULT_SNAP      = False # Start with grid snapping off
DEFAULT_GRID      = 16    # Starting grid size, in DAG units

CONNECT_ENDS      = True  # Look for nodes under the ends of the stroke
CONNECT_RADIUS    = 45    # How near an end has to be, in DAG units

DEBUG             = False # Print [DD] trace lines to the Script Editor
```

The `DEFAULT_` values seed the panel the first time only. After that the prefs file wins — delete it to pick them up again.

---

## Development

```
NukeDrawDots/
├── src/
│   ├── nuke_draw_dots.py         # Main tool — copy this to ~/.nuke/
│   └── menu.py                   # menu.py snippet to append
├── dist/
│   └── NukeDrawDots-1.1.0/       # Ready-to-install payload
├── tools/
│   ├── test_geometry.py          # Path maths, plain CPython
│   ├── test_import.py            # Qt layer + Dot wiring, headless
│   ├── test_static.py            # Qt symbol audit per Nuke version
│   └── build_dist.py             # Rebuilds dist/ and the release zip
├── README.md
└── LICENSE
```

Three suites, none needing a Nuke licence:

```
python tools/test_geometry.py     # 38 checks — RDP, right angles, grid, pipeline
python tools/test_import.py       # 78 checks — widgets, transform, Dot wiring
python tools/test_static.py       # 18 checks — Qt symbol audit, per Nuke version
```

`test_geometry.py` reads the functions under test straight out of `src/nuke_draw_dots.py`, between its `geometry - BEGIN` and `geometry - END` markers, so it tests the shipped code rather than a copy that can drift from it. Keep those markers where they are.

`test_static.py` is the cross-version one. Point it at the `python.exe` beside any Nuke and it imports the module against *that* Nuke's bundled Qt, then walks every `QtCore.*` / `QtGui.*` / `QtWidgets.*` name appearing in the source and resolves each one. A symbol that exists in PySide6 but not PySide2 fails here rather than in front of a user. It also drives the `_global_pos` shim with an event exposing both the Qt5 and Qt6 APIs and asserts it calls the one this binding actually ships — bytecode inspection can't tell those apart, since both names appear in the function either way.

```bash
for v in 14.1v8 15.2v9 16.0v8 16.1v1 17.0v4 17.1v1; do
    "/c/Program Files/Nuke$v/python.exe" tools/test_static.py
done
```

It deliberately never constructs a `QApplication`: Nuke's bundled interpreter hangs when it does, on both the `offscreen` and `minimal` platforms and with `QT_QPA_PLATFORM_PLUGIN_PATH` set. Everything before that point works, which is enough for the symbol audit.

`test_import.py` imports the real module with a stub `nuke` in `sys.modules` and a real `QApplication` on Qt's offscreen platform. It builds the overlay and the panel for real, forces a `paintEvent` through `grab()`, and checks the Dot chain's wiring, centring and undo balance against fake nodes. Run it with whatever interpreter has a PySide:

```
python tools/test_import.py
```

### Cutting a release

Bump `__version__` in `src/nuke_draw_dots.py`, then:

```
python tools/build_dist.py
```

That restages `dist/` and writes `dist/NukeDrawDots-<version>.zip`. The zip is gitignored; the folder is committed so the files stay readable on GitHub.

---

## License

MIT — see [LICENSE](LICENSE).
