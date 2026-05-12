# Archive Editor

A small GNOME / GTK4 / libadwaita app for adding anime, game, and review
entries to the absolking-archive personal website project.

## Prerequisites

You need Flatpak and `flatpak-builder` installed, plus the GNOME 50 runtime
and SDK. On Arch:

```bash
sudo pacman -S flatpak flatpak-builder
flatpak install --user flathub org.gnome.Platform//50 org.gnome.Sdk//50
```

(If you don't have Flathub set up:
`flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo`)

## Build & install (one command)

From this folder:

```bash
flatpak-builder --user --install --force-clean build-dir io.github.absolking.ArchiveEditor.json
```

That produces a build in `build-dir/` and installs the app. From now on it
shows up in your application launcher as **Archive Editor**.

## Run

From your launcher, or:

```bash
flatpak run io.github.absolking.ArchiveEditor
```

## Uninstall

```bash
flatpak uninstall --user io.github.absolking.ArchiveEditor
```

## Iterating during development

After editing source files, rebuild & reinstall the same way:

```bash
flatpak-builder --user --install --force-clean build-dir io.github.absolking.ArchiveEditor.json
```

The first build downloads the SDK; subsequent ones are fast (just copying files).

## File layout

- `io.github.absolking.ArchiveEditor.json` — Flatpak manifest
- `io.github.absolking.ArchiveEditor.desktop` — desktop launcher
- `io.github.absolking.ArchiveEditor.metainfo.xml` — AppStream metadata
- `io.github.absolking.ArchiveEditor.svg` — app icon
- `archive-editor` — shell launcher (becomes `/app/bin/archive-editor`)
- `src/main.py` — entry point
- `src/application.py` — `Adw.Application` subclass
- `src/window.py` — main window UI
- `src/archive_logic.py` — file I/O, no GUI deps

## Permissions

The app is sandboxed but has `--filesystem=home` so it can read & write
your project folder anywhere under `$HOME`. If you'd like to restrict it
further, edit the manifest's `finish-args`.
