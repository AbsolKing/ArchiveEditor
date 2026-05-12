"""Adw.Application that hosts the main window."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio  # noqa: E402

from window import ArchiveEditorWindow


APP_ID = "io.github.absolking.ArchiveEditor"


class ArchiveEditorApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = ArchiveEditorWindow(application=self)
        win.present()
