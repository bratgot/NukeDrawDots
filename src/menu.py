# -*- coding: utf-8 -*-
# menu.py - add these lines to your existing ~/.nuke/menu.py
# -------------------------------------------------------------
# Compatible with Nuke 14.1-15.x (PySide2) and 16+ (PySide6)

import nuke_draw_dots

toolbar = nuke.toolbar("Nodes")

# Arm the draw tool from the menu.
#
# The "shift+d" hotkey here is a fallback. While the Node Graph has focus the
# event filter claims Shift+D first, so the key and this command do the same
# thing; when the DAG is not focused the filter passes the key through and
# this command arms the tool anyway.
toolbar.addCommand(
    "Other/Draw Dots",
    "nuke_draw_dots.arm()",
    "shift+d",
    icon="Dot.png",
)
