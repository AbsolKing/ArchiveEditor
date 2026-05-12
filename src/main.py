#!/usr/bin/env python3
"""Archive Editor — entry point."""

import os
import sys

# Make sibling modules importable regardless of how the script is invoked
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

import gi  # noqa: E402
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from application import ArchiveEditorApp  # noqa: E402


def main():
    app = ArchiveEditorApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
