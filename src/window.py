"""Main window — libadwaita GUI for the Archive Editor."""

import json
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

import archive_logic


# ============================================================
# Constants
# ============================================================
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
BLOG_CATEGORIES = ["Notes", "Archive", "Design", "Roadmap"]


# ============================================================
# Settings persistence (last project folder)
# ============================================================
def _settings_path() -> Path:
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


# ============================================================
# Window
# ============================================================
class ArchiveEditorWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Archive Editor")
        self.set_default_size(760, 940)

        # Shared state
        self._settings = _load_settings()
        self.project_path = self._settings.get("project_path")

        # Database tab state
        self._db_kind = "anime"
        self._db_create_image_source = None
        self._db_create_image_filename = None
        self._db_edit_entries_cache = []
        self._db_edit_selected_entry = None
        self._db_edit_had_review = False

        # Blog tab state
        self._blog_posts_cache = []
        self._blog_selected_slug = None

        self._build_ui()

        # Reflect persisted project folder on both tabs
        self._refresh_project_rows()
        self._on_db_kind_changed()
        self._reload_db_edit_entries()
        self._reload_blog_posts()

    # ============================================================
    # Top-level layout
    # ============================================================
    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar_view)

        self.view_stack = Adw.ViewStack()

        header = Adw.HeaderBar()
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.view_stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        toolbar_view.add_top_bar(header)

        switcher_bar = Adw.ViewSwitcherBar()
        switcher_bar.set_stack(self.view_stack)
        switcher_bar.set_reveal(True)
        toolbar_view.add_bottom_bar(switcher_bar)

        toolbar_view.set_content(self.view_stack)

        db_page = self._build_database_view()
        blog_page = self._build_blog_view()
        self.view_stack.add_titled_with_icon(
            db_page, "database", "Database", "folder-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            blog_page, "blog", "Blog", "document-edit-symbolic"
        )

    # ============================================================
    # Shared widgets
    # ============================================================
    def _make_project_row(self):
        row = Adw.ActionRow(title="Folder", subtitle="No folder selected")
        btn = Gtk.Button(label="Choose…")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", self._on_choose_project)
        row.add_suffix(btn)
        row.set_activatable_widget(btn)
        return row

    def _refresh_project_rows(self):
        text = self.project_path or "No folder selected"
        if hasattr(self, "project_row_db"):
            self.project_row_db.set_subtitle(text)
        if hasattr(self, "project_row_blog"):
            self.project_row_blog.set_subtitle(text)

    def _make_text_area(self, parent_group, min_height):
        frame = Gtk.Frame()
        frame.set_size_request(-1, min_height)
        frame.add_css_class("card")
        parent_group.add(frame)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        frame.set_child(scroll)

        buffer = Gtk.TextBuffer()
        view = Gtk.TextView.new_with_buffer(buffer)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_top_margin(12)
        view.set_bottom_margin(12)
        view.set_left_margin(12)
        view.set_right_margin(12)
        scroll.set_child(view)
        return buffer, view

    # ============================================================
    # Shared event handlers
    # ============================================================
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
            return
        if folder:
            self.project_path = folder.get_path()
            self._refresh_project_rows()
            self._settings["project_path"] = self.project_path
            _save_settings(self._settings)
            self._reload_db_edit_entries()
            self._reload_blog_posts()

    def _toast(self, message: str, error: bool = False):
        toast = Adw.Toast.new(message)
        toast.set_timeout(5 if error else 3)
        self.toast_overlay.add_toast(toast)

    # ============================================================
    # DATABASE view
    # ============================================================
    def _build_database_view(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

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

        # Project
        proj_group = Adw.PreferencesGroup()
        proj_group.set_title("Project")
        proj_group.set_description("The website project folder")
        main.append(proj_group)
        self.project_row_db = self._make_project_row()
        proj_group.add(self.project_row_db)

        # Mode selector
        mode_group = Adw.PreferencesGroup(title="Mode")
        main.append(mode_group)

        self.db_mode_row = Adw.ComboRow(title="Action")
        self.db_mode_row.set_model(Gtk.StringList.new(["Create new entry", "Edit existing entry"]))
        self.db_mode_row.connect("notify::selected", self._on_db_mode_changed)
        mode_group.add(self.db_mode_row)

        # Edit-mode search (hidden in Create mode)
        self.db_search_group = Adw.PreferencesGroup(title="Find entry")
        main.append(self.db_search_group)

        self.db_edit_kind_row = Adw.ComboRow(title="Type")
        self.db_edit_kind_row.set_model(Gtk.StringList.new(["Anime", "Game"]))
        self.db_edit_kind_row.connect("notify::selected", self._on_db_edit_kind_changed)
        self.db_search_group.add(self.db_edit_kind_row)

        self.db_search_entry = Gtk.SearchEntry()
        self.db_search_entry.set_placeholder_text("Search by title…")
        self.db_search_entry.connect("search-changed", self._on_db_search_changed)

        search_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        search_wrap.set_margin_top(8)
        search_wrap.append(self.db_search_entry)

        self.db_results_listbox = Gtk.ListBox()
        self.db_results_listbox.add_css_class("boxed-list")
        self.db_results_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.db_results_listbox.connect("row-activated", self._on_db_result_activated)

        results_scroll = Gtk.ScrolledWindow()
        results_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        results_scroll.set_min_content_height(180)
        results_scroll.set_max_content_height(280)
        results_scroll.set_propagate_natural_height(True)
        results_scroll.set_child(self.db_results_listbox)
        search_wrap.append(results_scroll)
        self.db_search_group.add(search_wrap)
        self.db_search_group.set_visible(False)

        # Edit-mode locked info (hidden until an entry is selected)
        self.db_edit_info_group = Adw.PreferencesGroup(title="Editing")
        self.db_edit_info_group.set_visible(False)
        main.append(self.db_edit_info_group)

        self.db_edit_title_row = Adw.ActionRow(title="Title")
        self.db_edit_title_row.set_subtitle("")
        self.db_edit_info_group.add(self.db_edit_title_row)

        self.db_edit_image_row = Adw.ActionRow(title="Image")
        self.db_edit_image_row.set_subtitle("")
        self.db_edit_info_group.add(self.db_edit_image_row)

        # Create-mode fields (hidden in Edit mode)
        self.db_create_group = Adw.PreferencesGroup(title="New entry")
        main.append(self.db_create_group)

        self.db_create_kind_row = Adw.ComboRow(title="Type")
        self.db_create_kind_row.set_model(Gtk.StringList.new(["Anime", "Game"]))
        self.db_create_kind_row.connect("notify::selected", self._on_db_kind_changed)
        self.db_create_group.add(self.db_create_kind_row)

        self.db_create_title_row = Adw.EntryRow(title="Title")
        self.db_create_group.add(self.db_create_title_row)

        self.db_create_image_row = Adw.ActionRow(title="Image", subtitle="No image selected")
        img_btn = Gtk.Button(label="Browse…")
        img_btn.set_valign(Gtk.Align.CENTER)
        img_btn.connect("clicked", self._on_db_create_choose_image)
        self.db_create_image_row.add_suffix(img_btn)
        self.db_create_image_row.set_activatable_widget(img_btn)
        self.db_create_group.add(self.db_create_image_row)

        # Shared editable fields (visible in both modes)
        self.db_fields_group = Adw.PreferencesGroup(title="Fields")
        main.append(self.db_fields_group)

        self.db_subtype_combo_row = Adw.ComboRow(title="Subtype")
        self.db_subtype_combo_row.set_model(Gtk.StringList.new(ANIME_SUBTYPES))
        self.db_fields_group.add(self.db_subtype_combo_row)

        self.db_subtype_entry_row = Adw.EntryRow(title="Subtype  (e.g. RPG, Roguelike)")
        self.db_fields_group.add(self.db_subtype_entry_row)

        self.db_status_row = Adw.ComboRow(title="Status")
        self.db_status_row.set_model(Gtk.StringList.new([s[0] for s in ANIME_STATUSES]))
        self.db_fields_group.add(self.db_status_row)

        self.db_score_row = Adw.SpinRow.new_with_range(0, 10, 1)
        self.db_score_row.set_title("Score")
        self.db_score_row.set_subtitle("Out of 10")
        self.db_score_row.set_value(8)
        self.db_fields_group.add(self.db_score_row)

        self.db_unrated_row = Adw.SwitchRow(
            title="Unrated", subtitle="Don't include a score"
        )
        self.db_unrated_row.connect("notify::active", self._on_db_unrated_toggled)
        self.db_fields_group.add(self.db_unrated_row)

        self.db_progress_row = Adw.EntryRow(title="Progress  (e.g. 13 / 13)")
        self.db_fields_group.add(self.db_progress_row)

        self.db_note_row = Adw.EntryRow(title="Note  (clickable if a review is added)")
        self.db_fields_group.add(self.db_note_row)

        # Review section
        self.db_review_group = Adw.PreferencesGroup(title="Review")
        self.db_review_group.set_description(
            "Optional — creates /reviews/<kind>/<slug> and registers it in App.jsx"
        )
        main.append(self.db_review_group)

        self.db_review_switch_row = Adw.SwitchRow(
            title="Review page",
            subtitle="The note above becomes a clickable link",
        )
        self.db_review_switch_row.connect("notify::active", self._on_db_review_toggled)
        self.db_review_group.add(self.db_review_switch_row)

        review_text_group = Adw.PreferencesGroup()
        review_text_group.set_description("Each blank line starts a new paragraph")
        main.append(review_text_group)

        self.db_review_buffer, self.db_review_view = self._make_text_area(review_text_group, 220)
        self.db_review_view.set_sensitive(False)

        # Action buttons
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_row.set_halign(Gtk.Align.END)
        btn_row.set_margin_top(8)
        main.append(btn_row)

        clear_btn = Gtk.Button(label="Clear")
        clear_btn.connect("clicked", self._on_db_clear)
        btn_row.append(clear_btn)

        self.db_save_btn = Gtk.Button(label="Add Entry")
        self.db_save_btn.add_css_class("suggested-action")
        self.db_save_btn.connect("clicked", self._on_db_save_clicked)
        btn_row.append(self.db_save_btn)

        return scrolled

    # ============================================================
    # DATABASE handlers
    # ============================================================
    def _on_db_mode_changed(self, *_):
        is_edit = self.db_mode_row.get_selected() == 1
        self.db_search_group.set_visible(is_edit)
        self.db_create_group.set_visible(not is_edit)
        self.db_save_btn.set_label("Save Changes" if is_edit else "Add Entry")
        if is_edit:
            self._render_db_results(self._db_edit_entries_cache[:20])
        else:
            self._db_edit_selected_entry = None
            self.db_edit_info_group.set_visible(False)
            self._db_clear_create_fields()

    def _on_db_kind_changed(self, *_):
        idx = self.db_create_kind_row.get_selected()
        self._db_kind = "anime" if idx == 0 else "games"
        self._db_apply_kind_to_fields(self._db_kind)

    def _on_db_edit_kind_changed(self, *_):
        idx = self.db_edit_kind_row.get_selected()
        self._db_kind = "anime" if idx == 0 else "games"
        self._db_edit_selected_entry = None
        self.db_edit_info_group.set_visible(False)
        self._reload_db_edit_entries()

    def _db_apply_kind_to_fields(self, kind):
        if kind == "anime":
            statuses = ANIME_STATUSES
            self.db_subtype_combo_row.set_visible(True)
            self.db_subtype_entry_row.set_visible(False)
            self.db_progress_row.set_visible(True)
        else:
            statuses = GAME_STATUSES
            self.db_subtype_combo_row.set_visible(False)
            self.db_subtype_entry_row.set_visible(True)
            self.db_progress_row.set_visible(False)
        self.db_status_row.set_model(Gtk.StringList.new([s[0] for s in statuses]))
        self.db_status_row.set_selected(0)

    def _on_db_unrated_toggled(self, *_):
        self.db_score_row.set_sensitive(not self.db_unrated_row.get_active())

    def _on_db_review_toggled(self, *_):
        active = self.db_review_switch_row.get_active()
        self.db_review_view.set_sensitive(active)
        if active:
            self.db_review_view.grab_focus()

    def _on_db_create_choose_image(self, *_):
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
        dialog.open(self, None, self._on_db_create_image_selected)

    def _on_db_create_image_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if file:
            path = file.get_path()
            self._db_create_image_source = path
            self._db_create_image_filename = Path(path).name
            self.db_create_image_row.set_subtitle(self._db_create_image_filename)

    def _reload_db_edit_entries(self):
        if not self.project_path:
            self._db_edit_entries_cache = []
            self._render_db_results([])
            return
        try:
            self._db_edit_entries_cache = archive_logic.list_entries(
                self.project_path, self._db_kind
            )
        except Exception as e:
            self._db_edit_entries_cache = []
            self._toast(f"✗ {e}", error=True)
        self._on_db_search_changed()

    def _on_db_search_changed(self, *_):
        query = self.db_search_entry.get_text().strip().lower()
        if not self._db_edit_entries_cache:
            self._render_db_results([])
            return
        results = self._db_edit_entries_cache[:20] if not query else [
            e for e in self._db_edit_entries_cache
            if query in e.get("title", "").lower()
        ]
        self._render_db_results(results)

    def _render_db_results(self, results):
        child = self.db_results_listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.db_results_listbox.remove(child)
            child = nxt

        if not results:
            placeholder = Gtk.Label(label="No entries found")
            placeholder.add_css_class("dim-label")
            placeholder.set_margin_top(20)
            placeholder.set_margin_bottom(20)
            self.db_results_listbox.append(placeholder)
            return

        for entry in results:
            row = Adw.ActionRow()
            row.set_title(entry.get("title", "(no title)"))
            sub_parts = []
            if entry.get("status"):
                sub_parts.append(entry["status"])
            if entry.get("score") is not None:
                sub_parts.append(f"{entry['score']}/10")
            if sub_parts:
                row.set_subtitle("  ·  ".join(sub_parts))
            row.set_activatable(True)
            row._entry = entry
            self.db_results_listbox.append(row)

    def _on_db_result_activated(self, _listbox, row):
        entry = getattr(row, "_entry", None)
        if entry is None:
            return
        try:
            self._load_db_entry_into_form(entry["title"])
        except Exception as e:
            self._toast(f"✗ {e}", error=True)

    def _load_db_entry_into_form(self, title):
        data = archive_logic.load_entry_for_edit(
            self.project_path, self._db_kind, title
        )
        self._db_edit_selected_entry = data
        self._db_edit_had_review = data["has_review"]

        self.db_edit_title_row.set_subtitle(data["title"])
        self.db_edit_image_row.set_subtitle(data.get("image", "—"))
        self.db_edit_info_group.set_visible(True)

        existing_subtype = data.get("type", "")
        if self._db_kind == "anime":
            self.db_subtype_combo_row.set_visible(True)
            self.db_subtype_entry_row.set_visible(False)
            self.db_subtype_combo_row.set_selected(
                ANIME_SUBTYPES.index(existing_subtype) if existing_subtype in ANIME_SUBTYPES else 0
            )
        else:
            self.db_subtype_combo_row.set_visible(False)
            self.db_subtype_entry_row.set_visible(True)
            self.db_subtype_entry_row.set_text(existing_subtype)

        statuses = ANIME_STATUSES if self._db_kind == "anime" else GAME_STATUSES
        labels = [s[0] for s in statuses]
        self.db_status_row.set_model(Gtk.StringList.new(labels))
        existing_status = data.get("status", labels[0])
        self.db_status_row.set_selected(
            labels.index(existing_status) if existing_status in labels else 0
        )

        if data.get("score") is not None:
            self.db_unrated_row.set_active(False)
            self.db_score_row.set_value(float(data["score"]))
            self.db_score_row.set_sensitive(True)
        else:
            self.db_unrated_row.set_active(True)
            self.db_score_row.set_sensitive(False)

        self.db_progress_row.set_visible(self._db_kind == "anime")
        if self._db_kind == "anime":
            self.db_progress_row.set_text(data.get("progress", ""))

        self.db_note_row.set_text(data.get("note", ""))

        has = data["has_review"]
        self.db_review_switch_row.set_active(has)
        self.db_review_view.set_sensitive(has)
        self.db_review_buffer.set_text(data.get("review_text", ""))

    def _db_clear_create_fields(self):
        self.db_create_title_row.set_text("")
        self._db_create_image_source = None
        self._db_create_image_filename = None
        self.db_create_image_row.set_subtitle("No image selected")

    def _on_db_clear(self, *_):
        self._db_edit_selected_entry = None
        self._db_edit_had_review = False
        self.db_edit_info_group.set_visible(False)
        self._db_clear_create_fields()
        self.db_subtype_combo_row.set_selected(0)
        self.db_subtype_entry_row.set_text("")
        self.db_score_row.set_value(8)
        self.db_unrated_row.set_active(False)
        self.db_progress_row.set_text("")
        self.db_note_row.set_text("")
        self.db_review_switch_row.set_active(False)
        self.db_review_buffer.set_text("")
        self.db_search_entry.set_text("")

    def _on_db_save_clicked(self, *_):
        try:
            if self.db_mode_row.get_selected() == 1:
                self._save_db_edit()
            else:
                self._save_db_create()
        except Exception as e:
            self._toast(f"✗ {e}", error=True)

    def _save_db_create(self):
        if not self.project_path:
            raise ValueError("Select a project folder first")

        title = self.db_create_title_row.get_text().strip()
        if not title:
            raise ValueError("Title is required")

        if self._db_kind == "anime":
            subtype = ANIME_SUBTYPES[self.db_subtype_combo_row.get_selected()]
        else:
            subtype = self.db_subtype_entry_row.get_text().strip()
            if not subtype:
                raise ValueError("Subtype is required")

        statuses = ANIME_STATUSES if self._db_kind == "anime" else GAME_STATUSES
        status_label, status_key = statuses[self.db_status_row.get_selected()]

        score = None
        if not self.db_unrated_row.get_active():
            score = int(self.db_score_row.get_value())

        if not self._db_create_image_filename:
            raise ValueError("Select an image")

        fields = {
            "title": title,
            "subtype": subtype,
            "status_label": status_label,
            "status_key": status_key,
            "score": score,
            "image_filename": self._db_create_image_filename,
            "image_source": self._db_create_image_source,
            "note": self.db_note_row.get_text().strip(),
        }
        if self._db_kind == "anime":
            fields["progress"] = self.db_progress_row.get_text().strip()

        review_text = None
        if self.db_review_switch_row.get_active():
            start = self.db_review_buffer.get_start_iter()
            end = self.db_review_buffer.get_end_iter()
            review_text = self.db_review_buffer.get_text(start, end, False).strip()
            if not review_text:
                raise ValueError("Review is enabled but text is empty")

        result = archive_logic.add_entry(
            self.project_path, self._db_kind, fields, review_text
        )

        msg = f"✓ Added '{title}'"
        if review_text:
            msg += f"  +  /reviews/{self._db_kind}/{result['slug']}"
        self._toast(msg)
        self._on_db_clear()
        self._db_edit_entries_cache = []
        self._on_db_search_changed()

    def _save_db_edit(self):
        if not self.project_path:
            raise ValueError("Select a project folder first")
        if not self._db_edit_selected_entry:
            raise ValueError("No entry selected — search and click an entry first")

        title = self._db_edit_selected_entry["title"]

        if self._db_kind == "anime":
            subtype = ANIME_SUBTYPES[self.db_subtype_combo_row.get_selected()]
        else:
            subtype = self.db_subtype_entry_row.get_text().strip()
            if not subtype:
                raise ValueError("Subtype is required")

        statuses = ANIME_STATUSES if self._db_kind == "anime" else GAME_STATUSES
        status_label, status_key = statuses[self.db_status_row.get_selected()]

        score = None
        if not self.db_unrated_row.get_active():
            score = int(self.db_score_row.get_value())

        updates = {
            "subtype": subtype,
            "status_label": status_label,
            "status_key": status_key,
            "score": score,
            "note": self.db_note_row.get_text().strip(),
        }
        if self._db_kind == "anime":
            updates["progress"] = self.db_progress_row.get_text().strip()

        review_text = None
        if self.db_review_switch_row.get_active():
            start = self.db_review_buffer.get_start_iter()
            end = self.db_review_buffer.get_end_iter()
            review_text = self.db_review_buffer.get_text(start, end, False).strip()
            if not review_text:
                raise ValueError("Review is enabled but text is empty")

        result = archive_logic.edit_entry(
            self.project_path, self._db_kind, title, updates, review_text
        )

        msg = f"✓ Updated '{title}'"
        if result["has_review_now"] and not result["had_review"]:
            msg += f"  +  /reviews/{self._db_kind}/{result['slug']}"
        elif not result["has_review_now"] and result["had_review"]:
            msg += "  ·  review removed"
        self._toast(msg)

        self._db_edit_entries_cache = []
        self._reload_db_edit_entries()
        try:
            self._load_db_entry_into_form(title)
        except Exception:
            self._on_db_clear()

    # ============================================================
    # BLOG view
    # ============================================================
    def _build_blog_view(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

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

        # Project
        proj_group = Adw.PreferencesGroup()
        proj_group.set_title("Project")
        proj_group.set_description("The website project folder")
        main.append(proj_group)
        self.project_row_blog = self._make_project_row()
        proj_group.add(self.project_row_blog)

        # Mode selector
        mode_group = Adw.PreferencesGroup(title="Mode")
        main.append(mode_group)

        self.b_mode_row = Adw.ComboRow(title="Action")
        self.b_mode_row.set_model(Gtk.StringList.new(["Create new post", "Edit existing post"]))
        self.b_mode_row.connect("notify::selected", self._on_blog_mode_changed)
        mode_group.add(self.b_mode_row)

        # Edit-mode search (hidden in Create mode)
        self.b_search_group = Adw.PreferencesGroup(title="Find post")
        main.append(self.b_search_group)

        self.b_search_entry = Gtk.SearchEntry()
        self.b_search_entry.set_placeholder_text("Search by title…")
        self.b_search_entry.connect("search-changed", self._on_blog_search_changed)

        search_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        search_wrap.set_margin_top(8)
        search_wrap.append(self.b_search_entry)

        self.b_results_listbox = Gtk.ListBox()
        self.b_results_listbox.add_css_class("boxed-list")
        self.b_results_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.b_results_listbox.connect("row-activated", self._on_blog_result_activated)

        results_scroll = Gtk.ScrolledWindow()
        results_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        results_scroll.set_min_content_height(120)
        results_scroll.set_max_content_height(220)
        results_scroll.set_propagate_natural_height(True)
        results_scroll.set_child(self.b_results_listbox)
        search_wrap.append(results_scroll)
        self.b_search_group.add(search_wrap)
        self.b_search_group.set_visible(False)

        # Shared fields
        fields_group = Adw.PreferencesGroup(title="Post")
        main.append(fields_group)

        self.b_title_row = Adw.EntryRow(title="Title")
        fields_group.add(self.b_title_row)

        self.b_category_row = Adw.ComboRow(title="Category")
        self.b_category_row.set_model(Gtk.StringList.new(BLOG_CATEGORIES))
        fields_group.add(self.b_category_row)

        self.b_date_row = Adw.EntryRow(title="Date  (e.g. May 2026)")
        fields_group.add(self.b_date_row)

        self.b_excerpt_row = Adw.EntryRow(title="Excerpt  (shown in post list)")
        fields_group.add(self.b_excerpt_row)

        self.b_featured_row = Adw.SwitchRow(
            title="Featured",
            subtitle="Show on homepage in the Recent Posts section",
        )
        fields_group.add(self.b_featured_row)

        # Body text area
        body_group = Adw.PreferencesGroup(title="Content")
        body_group.set_description("Each blank line starts a new paragraph")
        main.append(body_group)

        self.b_body_buffer, self.b_body_view = self._make_text_area(body_group, 300)

        # Action buttons
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_row.set_halign(Gtk.Align.END)
        btn_row.set_margin_top(8)
        main.append(btn_row)

        clear_btn = Gtk.Button(label="Clear")
        clear_btn.connect("clicked", self._on_blog_clear)
        btn_row.append(clear_btn)

        self.b_save_btn = Gtk.Button(label="Add Post")
        self.b_save_btn.add_css_class("suggested-action")
        self.b_save_btn.connect("clicked", self._on_blog_save_clicked)
        btn_row.append(self.b_save_btn)

        return scrolled

    # ============================================================
    # BLOG handlers
    # ============================================================
    def _on_blog_mode_changed(self, *_):
        is_edit = self.b_mode_row.get_selected() == 1
        self.b_search_group.set_visible(is_edit)
        self.b_save_btn.set_label("Save Changes" if is_edit else "Add Post")
        if is_edit:
            self._render_blog_results(self._blog_posts_cache)
        else:
            self._blog_selected_slug = None
            self._on_blog_clear()

    def _reload_blog_posts(self):
        if not self.project_path:
            self._blog_posts_cache = []
            self._render_blog_results([])
            return
        try:
            self._blog_posts_cache = archive_logic.list_posts(self.project_path)
        except Exception as e:
            self._blog_posts_cache = []
            self._toast(f"✗ {e}", error=True)
        self._on_blog_search_changed()

    def _on_blog_search_changed(self, *_):
        query = self.b_search_entry.get_text().strip().lower()
        if not self._blog_posts_cache:
            self._render_blog_results([])
            return
        results = self._blog_posts_cache if not query else [
            p for p in self._blog_posts_cache
            if query in p.get("title", "").lower()
        ]
        self._render_blog_results(results)

    def _render_blog_results(self, results):
        child = self.b_results_listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.b_results_listbox.remove(child)
            child = nxt

        if not results:
            placeholder = Gtk.Label(label="No posts found")
            placeholder.add_css_class("dim-label")
            placeholder.set_margin_top(16)
            placeholder.set_margin_bottom(16)
            self.b_results_listbox.append(placeholder)
            return

        for post in results:
            row = Adw.ActionRow()
            row.set_title(post.get("title", "(no title)"))
            sub_parts = []
            if post.get("category"):
                sub_parts.append(post["category"])
            if post.get("date"):
                sub_parts.append(post["date"])
            if post.get("featured"):
                sub_parts.append("featured")
            if sub_parts:
                row.set_subtitle("  ·  ".join(sub_parts))
            row.set_activatable(True)
            row._post = post
            self.b_results_listbox.append(row)

    def _on_blog_result_activated(self, _listbox, row):
        post = getattr(row, "_post", None)
        if post is None:
            return
        try:
            self._load_post_into_form(post["slug"])
        except Exception as e:
            self._toast(f"✗ {e}", error=True)

    def _load_post_into_form(self, slug):
        data = archive_logic.load_post_for_edit(self.project_path, slug)
        self._blog_selected_slug = slug

        self.b_title_row.set_text(data.get("title", ""))
        category = data.get("category", "Notes")
        self.b_category_row.set_selected(
            BLOG_CATEGORIES.index(category) if category in BLOG_CATEGORIES else 0
        )
        self.b_date_row.set_text(data.get("date", ""))
        self.b_excerpt_row.set_text(data.get("excerpt", ""))
        self.b_featured_row.set_active(bool(data.get("featured")))
        self.b_body_buffer.set_text(data.get("body_text", ""))

    def _on_blog_clear(self, *_):
        self._blog_selected_slug = None
        self.b_title_row.set_text("")
        self.b_category_row.set_selected(0)
        self.b_date_row.set_text("")
        self.b_excerpt_row.set_text("")
        self.b_featured_row.set_active(False)
        self.b_body_buffer.set_text("")
        self.b_search_entry.set_text("")

    def _on_blog_save_clicked(self, *_):
        try:
            self._save_blog_post()
        except Exception as e:
            self._toast(f"✗ {e}", error=True)

    def _save_blog_post(self):
        if not self.project_path:
            raise ValueError("Select a project folder first")

        title = self.b_title_row.get_text().strip()
        if not title:
            raise ValueError("Title is required")

        category = BLOG_CATEGORIES[self.b_category_row.get_selected()]
        date = self.b_date_row.get_text().strip()
        if not date:
            raise ValueError("Date is required")

        excerpt = self.b_excerpt_row.get_text().strip()
        featured = self.b_featured_row.get_active()

        start = self.b_body_buffer.get_start_iter()
        end = self.b_body_buffer.get_end_iter()
        body_text = self.b_body_buffer.get_text(start, end, False).strip()
        if not body_text:
            raise ValueError("Post content is required")

        fields = {
            "title": title,
            "excerpt": excerpt,
            "date": date,
            "category": category,
            "featured": featured,
            "body_text": body_text,
        }

        is_edit = self.b_mode_row.get_selected() == 1

        if is_edit:
            if not self._blog_selected_slug:
                raise ValueError("No post selected — search and click a post first")
            archive_logic.edit_post(self.project_path, self._blog_selected_slug, fields)
            self._toast(f"✓ Updated '{title}'")
        else:
            result = archive_logic.add_post(self.project_path, fields)
            self._toast(f"✓ Added post '{title}'  →  /blog/{result['slug']}")
            self._on_blog_clear()

        self._reload_blog_posts()
