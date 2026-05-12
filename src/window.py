"""Main window — libadwaita GUI for the Archive Editor."""

import json
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

import archive_logic


# Status mappings — kept here in the GUI module since they're UI-presentation concerns
ANIME_STATUSES = [
    ("Completed", "completed"),
    ("Watching",  "watching"),
    ("Planning",  "planned"),
    ("On hold",   "on-hold"),
]
GAME_STATUSES = [
    ("Played",   "played"),
    ("Playing",  "playing"),
    ("Backlog",  "backlog"),
]
ANIME_SUBTYPES = ["TV", "OVA", "Movie", "ONA", "Special"]


def _settings_path() -> Path:
    """Per-user JSON for remembering things like the last project folder."""
    return Path(GLib.get_user_config_dir()) / "settings.json"


def _load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_settings(data: dict):
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


class ArchiveEditorWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Archive Editor")
        self.set_default_size(720, 920)

        self._settings = _load_settings()
        self.project_path: str | None = self._settings.get("project_path")
        self.image_source_path: str | None = None
        self.image_filename: str | None = None
        self.kind: str = "anime"

        self._build_ui()

        if self.project_path:
            self.project_row.set_subtitle(self.project_path)

        self._on_kind_changed()

    # ============================================================
    # Layout
    # ============================================================
    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar_view)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Archive Editor"))
        toolbar_view.add_top_bar(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar_view.set_content(scrolled)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(640)
        clamp.set_tightening_threshold(580)
        scrolled.set_child(clamp)

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        main.set_margin_top(24)
        main.set_margin_bottom(24)
        main.set_margin_start(12)
        main.set_margin_end(12)
        clamp.set_child(main)

        # ── Project ──
        proj_group = Adw.PreferencesGroup()
        proj_group.set_title("Project")
        proj_group.set_description(
            "The website project folder where files will be edited"
        )
        main.append(proj_group)

        self.project_row = Adw.ActionRow(title="Folder", subtitle="No folder selected")
        choose_proj = Gtk.Button(label="Choose…")
        choose_proj.set_valign(Gtk.Align.CENTER)
        choose_proj.connect("clicked", self._on_choose_project)
        self.project_row.add_suffix(choose_proj)
        self.project_row.set_activatable_widget(choose_proj)
        proj_group.add(self.project_row)

        # ── Entry ──
        entry_group = Adw.PreferencesGroup()
        entry_group.set_title("Entry")
        main.append(entry_group)

        # Type
        self.kind_row = Adw.ComboRow(title="Type")
        self.kind_row.set_model(Gtk.StringList.new(["Anime", "Game"]))
        self.kind_row.connect("notify::selected", self._on_kind_changed)
        entry_group.add(self.kind_row)

        # Title
        self.title_row = Adw.EntryRow(title="Title")
        entry_group.add(self.title_row)

        # Subtype — combo for anime, free-text for games
        self.subtype_combo_row = Adw.ComboRow(title="Subtype")
        self.subtype_combo_row.set_model(Gtk.StringList.new(ANIME_SUBTYPES))
        entry_group.add(self.subtype_combo_row)

        self.subtype_entry_row = Adw.EntryRow(title="Subtype  (e.g. RPG, Roguelike)")
        entry_group.add(self.subtype_entry_row)

        # Status
        self.status_row = Adw.ComboRow(title="Status")
        self.status_row.set_model(Gtk.StringList.new([s[0] for s in ANIME_STATUSES]))
        entry_group.add(self.status_row)

        # Score
        self.score_row = Adw.SpinRow.new_with_range(0, 10, 1)
        self.score_row.set_title("Score")
        self.score_row.set_subtitle("Out of 10")
        self.score_row.set_value(8)
        entry_group.add(self.score_row)

        self.unrated_row = Adw.SwitchRow(title="Unrated", subtitle="Don't include a score")
        self.unrated_row.connect("notify::active", self._on_unrated_toggled)
        entry_group.add(self.unrated_row)

        # Progress (anime only)
        self.progress_row = Adw.EntryRow(title="Progress  (e.g. 13 / 13)")
        entry_group.add(self.progress_row)

        # Image
        self.image_row = Adw.ActionRow(title="Image", subtitle="No image selected")
        choose_img = Gtk.Button(label="Browse…")
        choose_img.set_valign(Gtk.Align.CENTER)
        choose_img.connect("clicked", self._on_choose_image)
        self.image_row.add_suffix(choose_img)
        self.image_row.set_activatable_widget(choose_img)
        entry_group.add(self.image_row)

        # Note
        self.note_row = Adw.EntryRow(title="Note  (clickable if a review is added)")
        entry_group.add(self.note_row)

        # ── Review ──
        review_group = Adw.PreferencesGroup()
        review_group.set_title("Review")
        review_group.set_description(
            "Optional — creates /reviews/<kind>/<slug> and registers it in App.jsx"
        )
        main.append(review_group)

        self.review_switch_row = Adw.SwitchRow(
            title="Create review page",
            subtitle="The note above becomes a clickable link to this review",
        )
        self.review_switch_row.connect("notify::active", self._on_review_toggled)
        review_group.add(self.review_switch_row)

        text_group = Adw.PreferencesGroup()
        text_group.set_description("Each blank line in the text below starts a new paragraph")
        main.append(text_group)

        text_frame = Gtk.Frame()
        text_frame.set_size_request(-1, 220)
        text_frame.add_css_class("card")
        text_group.add(text_frame)

        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        text_frame.set_child(text_scroll)

        self.review_buffer = Gtk.TextBuffer()
        self.review_view = Gtk.TextView.new_with_buffer(self.review_buffer)
        self.review_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.review_view.set_top_margin(12)
        self.review_view.set_bottom_margin(12)
        self.review_view.set_left_margin(12)
        self.review_view.set_right_margin(12)
        self.review_view.set_sensitive(False)
        text_scroll.set_child(self.review_view)

        # ── Bottom buttons ──
        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_row.set_halign(Gtk.Align.END)
        button_row.set_margin_top(8)
        main.append(button_row)

        clear_btn = Gtk.Button(label="Clear")
        clear_btn.connect("clicked", self._on_clear)
        button_row.append(clear_btn)

        add_btn = Gtk.Button(label="Add Entry")
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._on_add_clicked)
        button_row.append(add_btn)

    # ============================================================
    # Event handlers
    # ============================================================
    def _on_kind_changed(self, *_):
        idx = self.kind_row.get_selected()
        self.kind = "anime" if idx == 0 else "games"
        if self.kind == "anime":
            statuses = ANIME_STATUSES
            self.subtype_combo_row.set_visible(True)
            self.subtype_entry_row.set_visible(False)
            self.progress_row.set_visible(True)
        else:
            statuses = GAME_STATUSES
            self.subtype_combo_row.set_visible(False)
            self.subtype_entry_row.set_visible(True)
            self.progress_row.set_visible(False)

        self.status_row.set_model(Gtk.StringList.new([s[0] for s in statuses]))
        self.status_row.set_selected(0)

    def _on_unrated_toggled(self, *_):
        self.score_row.set_sensitive(not self.unrated_row.get_active())

    def _on_review_toggled(self, *_):
        active = self.review_switch_row.get_active()
        self.review_view.set_sensitive(active)
        if active:
            self.review_view.grab_focus()

    def _on_choose_project(self, *_):
        dialog = Gtk.FileDialog()
        dialog.set_title("Select project folder")
        if self.project_path and Path(self.project_path).exists():
            dialog.set_initial_folder(Gio.File.new_for_path(self.project_path))
        dialog.select_folder(self, None, self._on_project_selected)

    def _on_project_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return  # user cancelled
        if folder:
            self.project_path = folder.get_path()
            self.project_row.set_subtitle(self.project_path)
            self._settings["project_path"] = self.project_path
            _save_settings(self._settings)

    def _on_choose_image(self, *_):
        dialog = Gtk.FileDialog()
        dialog.set_title("Select image")

        f = Gtk.FileFilter()
        f.set_name("Images")
        for mime in ("image/png", "image/jpeg", "image/webp", "image/gif"):
            f.add_mime_type(mime)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dialog.set_filters(filters)
        dialog.set_default_filter(f)

        dialog.open(self, None, self._on_image_selected)

    def _on_image_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if file:
            path = file.get_path()
            self.image_source_path = path
            self.image_filename = Path(path).name
            self.image_row.set_subtitle(self.image_filename)

    def _on_clear(self, *_):
        self.title_row.set_text("")
        self.subtype_entry_row.set_text("")
        self.subtype_combo_row.set_selected(0)
        self.score_row.set_value(8)
        self.unrated_row.set_active(False)
        self.progress_row.set_text("")
        self.image_filename = None
        self.image_source_path = None
        self.image_row.set_subtitle("No image selected")
        self.note_row.set_text("")
        self.review_switch_row.set_active(False)
        self.review_buffer.set_text("")

    # ============================================================
    # Add entry
    # ============================================================
    def _on_add_clicked(self, *_):
        try:
            self._add_entry()
        except Exception as e:
            self._toast(f"✗ {e}", error=True)

    def _add_entry(self):
        if not self.project_path:
            raise ValueError("Select a project folder first")

        title = self.title_row.get_text().strip()
        if not title:
            raise ValueError("Title is required")

        if self.kind == "anime":
            subtype = ANIME_SUBTYPES[self.subtype_combo_row.get_selected()]
        else:
            subtype = self.subtype_entry_row.get_text().strip()
            if not subtype:
                raise ValueError("Subtype is required")

        statuses = ANIME_STATUSES if self.kind == "anime" else GAME_STATUSES
        status_label, status_key = statuses[self.status_row.get_selected()]

        score = None
        if not self.unrated_row.get_active():
            score = int(self.score_row.get_value())

        if not self.image_filename:
            raise ValueError("Select an image")

        fields = {
            "title": title,
            "subtype": subtype,
            "status_label": status_label,
            "status_key": status_key,
            "score": score,
            "image_filename": self.image_filename,
            "image_source": self.image_source_path,
            "note": self.note_row.get_text().strip(),
        }
        if self.kind == "anime":
            fields["progress"] = self.progress_row.get_text().strip()

        review_text = None
        if self.review_switch_row.get_active():
            start = self.review_buffer.get_start_iter()
            end = self.review_buffer.get_end_iter()
            review_text = self.review_buffer.get_text(start, end, False).strip()
            if not review_text:
                raise ValueError("Review is enabled but text is empty")

        result = archive_logic.add_entry(
            self.project_path, self.kind, fields, review_text
        )

        msg = f"✓ Added '{title}'"
        if review_text:
            msg += f"  +  /reviews/{self.kind}/{result['slug']}"
        self._toast(msg)
        self._on_clear()

    # ============================================================
    # Toast
    # ============================================================
    def _toast(self, message: str, error: bool = False):
        toast = Adw.Toast.new(message)
        toast.set_timeout(5 if error else 3)
        self.toast_overlay.add_toast(toast)
