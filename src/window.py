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

        # Per-tab state
        self._create_image_source = None
        self._create_image_filename = None
        self._create_kind = "anime"

        self._edit_kind = "anime"
        self._edit_entries_cache = []
        self._edit_selected_entry = None  # dict from list_entries
        self._edit_had_review = False

        self._build_ui()

        # Reflect persisted project folder on both tabs
        self._refresh_project_rows()
        self._on_create_kind_changed()
        self._on_edit_kind_changed()

    # ============================================================
    # Top-level layout
    # ============================================================
    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar_view)

        # View stack must exist before we wire it to the switcher
        self.view_stack = Adw.ViewStack()

        header = Adw.HeaderBar()
        # ViewSwitcher in the header title
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.view_stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        toolbar_view.add_top_bar(header)

        # Compact switcher bar shown when window is narrow
        switcher_bar = Adw.ViewSwitcherBar()
        switcher_bar.set_stack(self.view_stack)
        switcher_bar.set_reveal(True)
        toolbar_view.add_bottom_bar(switcher_bar)

        toolbar_view.set_content(self.view_stack)

        # Add the two pages
        create_page = self._build_create_view()
        edit_page = self._build_edit_view()
        self.view_stack.add_titled_with_icon(
            create_page, "create", "Create", "list-add-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            edit_page, "edit", "Edit", "document-edit-symbolic"
        )

    # ============================================================
    # Shared widgets
    # ============================================================
    def _make_project_row(self):
        """A project-folder row. Multiple instances exist (one per tab),
        all reading/writing the same self.project_path state."""
        row = Adw.ActionRow(title="Folder", subtitle="No folder selected")
        btn = Gtk.Button(label="Choose…")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", self._on_choose_project)
        row.add_suffix(btn)
        row.set_activatable_widget(btn)
        return row

    def _refresh_project_rows(self):
        text = self.project_path or "No folder selected"
        if hasattr(self, "project_row_create"):
            self.project_row_create.set_subtitle(text)
        if hasattr(self, "project_row_edit"):
            self.project_row_edit.set_subtitle(text)

    # ============================================================
    # CREATE view
    # ============================================================
    def _build_create_view(self):
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
        self.project_row_create = self._make_project_row()
        proj_group.add(self.project_row_create)

        # Entry
        entry_group = Adw.PreferencesGroup(title="New entry")
        main.append(entry_group)

        self.c_kind_row = Adw.ComboRow(title="Type")
        self.c_kind_row.set_model(Gtk.StringList.new(["Anime", "Game"]))
        self.c_kind_row.connect("notify::selected", self._on_create_kind_changed)
        entry_group.add(self.c_kind_row)

        self.c_title_row = Adw.EntryRow(title="Title")
        entry_group.add(self.c_title_row)

        self.c_subtype_combo_row = Adw.ComboRow(title="Subtype")
        self.c_subtype_combo_row.set_model(Gtk.StringList.new(ANIME_SUBTYPES))
        entry_group.add(self.c_subtype_combo_row)

        self.c_subtype_entry_row = Adw.EntryRow(title="Subtype  (e.g. RPG, Roguelike)")
        entry_group.add(self.c_subtype_entry_row)

        self.c_status_row = Adw.ComboRow(title="Status")
        self.c_status_row.set_model(Gtk.StringList.new([s[0] for s in ANIME_STATUSES]))
        entry_group.add(self.c_status_row)

        self.c_score_row = Adw.SpinRow.new_with_range(0, 10, 1)
        self.c_score_row.set_title("Score")
        self.c_score_row.set_subtitle("Out of 10")
        self.c_score_row.set_value(8)
        entry_group.add(self.c_score_row)

        self.c_unrated_row = Adw.SwitchRow(
            title="Unrated", subtitle="Don't include a score"
        )
        self.c_unrated_row.connect("notify::active", self._on_create_unrated_toggled)
        entry_group.add(self.c_unrated_row)

        self.c_progress_row = Adw.EntryRow(title="Progress  (e.g. 13 / 13)")
        entry_group.add(self.c_progress_row)

        self.c_image_row = Adw.ActionRow(title="Image", subtitle="No image selected")
        img_btn = Gtk.Button(label="Browse…")
        img_btn.set_valign(Gtk.Align.CENTER)
        img_btn.connect("clicked", self._on_create_choose_image)
        self.c_image_row.add_suffix(img_btn)
        self.c_image_row.set_activatable_widget(img_btn)
        entry_group.add(self.c_image_row)

        self.c_note_row = Adw.EntryRow(title="Note  (clickable if a review is added)")
        entry_group.add(self.c_note_row)

        # Review section
        rev_group = Adw.PreferencesGroup(title="Review")
        rev_group.set_description(
            "Optional — creates /reviews/<kind>/<slug> and registers it in App.jsx"
        )
        main.append(rev_group)

        self.c_review_switch_row = Adw.SwitchRow(
            title="Create review page",
            subtitle="The note above becomes a clickable link",
        )
        self.c_review_switch_row.connect("notify::active", self._on_create_review_toggled)
        rev_group.add(self.c_review_switch_row)

        text_group = Adw.PreferencesGroup()
        text_group.set_description("Each blank line in the text below starts a new paragraph")
        main.append(text_group)

        self.c_review_buffer, self.c_review_view = self._make_text_area(text_group, 220)
        self.c_review_view.set_sensitive(False)

        # Action buttons
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_row.set_halign(Gtk.Align.END)
        btn_row.set_margin_top(8)
        main.append(btn_row)

        clear = Gtk.Button(label="Clear")
        clear.connect("clicked", self._on_create_clear)
        btn_row.append(clear)

        add = Gtk.Button(label="Add Entry")
        add.add_css_class("suggested-action")
        add.connect("clicked", self._on_add_clicked)
        btn_row.append(add)

        return scrolled

    # ============================================================
    # EDIT view
    # ============================================================
    def _build_edit_view(self):
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
        self.project_row_edit = self._make_project_row()
        proj_group.add(self.project_row_edit)

        # Search section
        search_group = Adw.PreferencesGroup(title="Find entry")
        main.append(search_group)

        self.e_kind_row = Adw.ComboRow(title="Type")
        self.e_kind_row.set_model(Gtk.StringList.new(["Anime", "Game"]))
        self.e_kind_row.connect("notify::selected", self._on_edit_kind_changed)
        search_group.add(self.e_kind_row)

        # SearchEntry sits inside its own row-like container so it lines up
        self.e_search_entry = Gtk.SearchEntry()
        self.e_search_entry.set_placeholder_text("Search by title…")
        self.e_search_entry.connect("search-changed", self._on_edit_search_changed)

        search_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        search_wrap.set_margin_top(8)
        search_wrap.append(self.e_search_entry)

        # Results listbox in a card
        self.e_results_listbox = Gtk.ListBox()
        self.e_results_listbox.add_css_class("boxed-list")
        self.e_results_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.e_results_listbox.connect("row-activated", self._on_edit_result_activated)

        self.e_results_scroll = Gtk.ScrolledWindow()
        self.e_results_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.e_results_scroll.set_min_content_height(180)
        self.e_results_scroll.set_max_content_height(280)
        self.e_results_scroll.set_propagate_natural_height(True)
        self.e_results_scroll.set_child(self.e_results_listbox)
        search_wrap.append(self.e_results_scroll)

        main.append(search_wrap)

        # ── Selected-entry section (hidden until something is loaded) ──
        self.e_form_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.e_form_box.set_visible(False)
        main.append(self.e_form_box)

        info_group = Adw.PreferencesGroup(title="Editing")
        self.e_form_box.append(info_group)

        self.e_title_row = Adw.ActionRow(title="Title")
        self.e_title_row.set_subtitle("")
        self.e_form_box_title_row = self.e_title_row
        info_group.add(self.e_title_row)

        self.e_image_row = Adw.ActionRow(title="Image")
        self.e_image_row.set_subtitle("")
        info_group.add(self.e_image_row)

        fields_group = Adw.PreferencesGroup(title="Fields")
        self.e_form_box.append(fields_group)

        self.e_subtype_combo_row = Adw.ComboRow(title="Subtype")
        self.e_subtype_combo_row.set_model(Gtk.StringList.new(ANIME_SUBTYPES))
        fields_group.add(self.e_subtype_combo_row)

        self.e_subtype_entry_row = Adw.EntryRow(title="Subtype  (e.g. RPG, Roguelike)")
        fields_group.add(self.e_subtype_entry_row)

        self.e_status_row = Adw.ComboRow(title="Status")
        self.e_status_row.set_model(Gtk.StringList.new([s[0] for s in ANIME_STATUSES]))
        fields_group.add(self.e_status_row)

        self.e_score_row = Adw.SpinRow.new_with_range(0, 10, 1)
        self.e_score_row.set_title("Score")
        self.e_score_row.set_subtitle("Out of 10")
        self.e_score_row.set_value(8)
        fields_group.add(self.e_score_row)

        self.e_unrated_row = Adw.SwitchRow(
            title="Unrated", subtitle="Don't include a score"
        )
        self.e_unrated_row.connect("notify::active", self._on_edit_unrated_toggled)
        fields_group.add(self.e_unrated_row)

        self.e_progress_row = Adw.EntryRow(title="Progress  (e.g. 13 / 13)")
        fields_group.add(self.e_progress_row)

        self.e_note_row = Adw.EntryRow(title="Note")
        fields_group.add(self.e_note_row)

        # Review
        rev_group = Adw.PreferencesGroup(title="Review")
        rev_group.set_description(
            "Toggling off removes /reviews/<kind>/<slug> and unregisters it from App.jsx"
        )
        self.e_form_box.append(rev_group)

        self.e_review_switch_row = Adw.SwitchRow(
            title="Has review page",
            subtitle="Note becomes a clickable link to the review",
        )
        self.e_review_switch_row.connect("notify::active", self._on_edit_review_toggled)
        rev_group.add(self.e_review_switch_row)

        text_group = Adw.PreferencesGroup()
        text_group.set_description("Each blank line starts a new paragraph")
        self.e_form_box.append(text_group)

        self.e_review_buffer, self.e_review_view = self._make_text_area(text_group, 220)
        self.e_review_view.set_sensitive(False)

        # Save button
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_row.set_halign(Gtk.Align.END)
        btn_row.set_margin_top(8)
        self.e_form_box.append(btn_row)

        save = Gtk.Button(label="Save Changes")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._on_save_clicked)
        btn_row.append(save)

        return scrolled

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
            # Refresh the edit-tab entries cache if user is on edit view
            self._reload_edit_entries()

    def _toast(self, message: str, error: bool = False):
        toast = Adw.Toast.new(message)
        toast.set_timeout(5 if error else 3)
        self.toast_overlay.add_toast(toast)

    # ============================================================
    # CREATE handlers
    # ============================================================
    def _on_create_kind_changed(self, *_):
        idx = self.c_kind_row.get_selected()
        self._create_kind = "anime" if idx == 0 else "games"
        if self._create_kind == "anime":
            statuses = ANIME_STATUSES
            self.c_subtype_combo_row.set_visible(True)
            self.c_subtype_entry_row.set_visible(False)
            self.c_progress_row.set_visible(True)
        else:
            statuses = GAME_STATUSES
            self.c_subtype_combo_row.set_visible(False)
            self.c_subtype_entry_row.set_visible(True)
            self.c_progress_row.set_visible(False)
        self.c_status_row.set_model(Gtk.StringList.new([s[0] for s in statuses]))
        self.c_status_row.set_selected(0)

    def _on_create_unrated_toggled(self, *_):
        self.c_score_row.set_sensitive(not self.c_unrated_row.get_active())

    def _on_create_review_toggled(self, *_):
        active = self.c_review_switch_row.get_active()
        self.c_review_view.set_sensitive(active)
        if active:
            self.c_review_view.grab_focus()

    def _on_create_choose_image(self, *_):
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
        dialog.open(self, None, self._on_create_image_selected)

    def _on_create_image_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if file:
            path = file.get_path()
            self._create_image_source = path
            self._create_image_filename = Path(path).name
            self.c_image_row.set_subtitle(self._create_image_filename)

    def _on_create_clear(self, *_):
        self.c_title_row.set_text("")
        self.c_subtype_entry_row.set_text("")
        self.c_subtype_combo_row.set_selected(0)
        self.c_score_row.set_value(8)
        self.c_unrated_row.set_active(False)
        self.c_progress_row.set_text("")
        self._create_image_filename = None
        self._create_image_source = None
        self.c_image_row.set_subtitle("No image selected")
        self.c_note_row.set_text("")
        self.c_review_switch_row.set_active(False)
        self.c_review_buffer.set_text("")

    def _on_add_clicked(self, *_):
        try:
            self._add_entry()
        except Exception as e:
            self._toast(f"✗ {e}", error=True)

    def _add_entry(self):
        if not self.project_path:
            raise ValueError("Select a project folder first")

        title = self.c_title_row.get_text().strip()
        if not title:
            raise ValueError("Title is required")

        if self._create_kind == "anime":
            subtype = ANIME_SUBTYPES[self.c_subtype_combo_row.get_selected()]
        else:
            subtype = self.c_subtype_entry_row.get_text().strip()
            if not subtype:
                raise ValueError("Subtype is required")

        statuses = ANIME_STATUSES if self._create_kind == "anime" else GAME_STATUSES
        status_label, status_key = statuses[self.c_status_row.get_selected()]

        score = None
        if not self.c_unrated_row.get_active():
            score = int(self.c_score_row.get_value())

        if not self._create_image_filename:
            raise ValueError("Select an image")

        fields = {
            "title": title,
            "subtype": subtype,
            "status_label": status_label,
            "status_key": status_key,
            "score": score,
            "image_filename": self._create_image_filename,
            "image_source": self._create_image_source,
            "note": self.c_note_row.get_text().strip(),
        }
        if self._create_kind == "anime":
            fields["progress"] = self.c_progress_row.get_text().strip()

        review_text = None
        if self.c_review_switch_row.get_active():
            start = self.c_review_buffer.get_start_iter()
            end = self.c_review_buffer.get_end_iter()
            review_text = self.c_review_buffer.get_text(start, end, False).strip()
            if not review_text:
                raise ValueError("Review is enabled but text is empty")

        result = archive_logic.add_entry(
            self.project_path, self._create_kind, fields, review_text
        )

        msg = f"✓ Added '{title}'"
        if review_text:
            msg += f"  +  /reviews/{self._create_kind}/{result['slug']}"
        self._toast(msg)
        self._on_create_clear()

        # The edit-tab cache is now stale
        self._edit_entries_cache = []
        self._on_edit_search_changed()

    # ============================================================
    # EDIT handlers
    # ============================================================
    def _on_edit_kind_changed(self, *_):
        idx = self.e_kind_row.get_selected()
        self._edit_kind = "anime" if idx == 0 else "games"
        # Clear current selection — the entry isn't valid for the new kind
        self._clear_edit_form()
        self._reload_edit_entries()

    def _reload_edit_entries(self):
        """Refresh the entries cache for the current kind, then re-render results."""
        if not self.project_path:
            self._edit_entries_cache = []
            self._render_edit_results([])
            return
        try:
            self._edit_entries_cache = archive_logic.list_entries(
                self.project_path, self._edit_kind
            )
        except Exception as e:
            self._edit_entries_cache = []
            self._toast(f"✗ {e}", error=True)
        self._on_edit_search_changed()

    def _on_edit_search_changed(self, *_):
        query = self.e_search_entry.get_text().strip().lower()
        if not self._edit_entries_cache:
            self._render_edit_results([])
            return
        if not query:
            # Show first 20 entries when no query, to give some context
            results = self._edit_entries_cache[:20]
        else:
            results = [
                e for e in self._edit_entries_cache
                if query in e.get("title", "").lower()
            ]
        self._render_edit_results(results)

    def _render_edit_results(self, results):
        # Clear existing rows
        child = self.e_results_listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.e_results_listbox.remove(child)
            child = nxt

        if not results:
            placeholder = Gtk.Label(label="No entries found")
            placeholder.add_css_class("dim-label")
            placeholder.set_margin_top(20)
            placeholder.set_margin_bottom(20)
            self.e_results_listbox.append(placeholder)
            return

        for entry in results:
            row = Adw.ActionRow()
            row.set_title(entry.get("title", "(no title)"))
            sub_parts = []
            if entry.get("status"):
                sub_parts.append(entry["status"])
            if entry.get("score") is not None:
                sub_parts.append(f"{entry['score']}/10")
            elif "score" not in entry:
                sub_parts.append("unrated")
            if sub_parts:
                row.set_subtitle("  ·  ".join(sub_parts))
            row.set_activatable(True)
            row._entry = entry  # stash data for the activate handler
            self.e_results_listbox.append(row)

    def _on_edit_result_activated(self, _listbox, row):
        entry = getattr(row, "_entry", None)
        if entry is None:
            return
        try:
            self._load_entry_into_form(entry["title"])
        except Exception as e:
            self._toast(f"✗ {e}", error=True)

    def _load_entry_into_form(self, title):
        data = archive_logic.load_entry_for_edit(
            self.project_path, self._edit_kind, title
        )
        self._edit_selected_entry = data
        self._edit_had_review = data["has_review"]

        # Locked fields
        self.e_title_row.set_subtitle(data["title"])
        self.e_image_row.set_subtitle(data.get("image", "—"))

        # Subtype
        existing_subtype = data.get("type", "")
        if self._edit_kind == "anime":
            self.e_subtype_combo_row.set_visible(True)
            self.e_subtype_entry_row.set_visible(False)
            if existing_subtype in ANIME_SUBTYPES:
                self.e_subtype_combo_row.set_selected(
                    ANIME_SUBTYPES.index(existing_subtype)
                )
            else:
                self.e_subtype_combo_row.set_selected(0)
        else:
            self.e_subtype_combo_row.set_visible(False)
            self.e_subtype_entry_row.set_visible(True)
            self.e_subtype_entry_row.set_text(existing_subtype)

        # Status
        statuses = ANIME_STATUSES if self._edit_kind == "anime" else GAME_STATUSES
        labels = [s[0] for s in statuses]
        self.e_status_row.set_model(Gtk.StringList.new(labels))
        existing_status = data.get("status", labels[0])
        if existing_status in labels:
            self.e_status_row.set_selected(labels.index(existing_status))
        else:
            self.e_status_row.set_selected(0)

        # Score
        if "score" in data and data.get("score") is not None:
            self.e_unrated_row.set_active(False)
            self.e_score_row.set_value(float(data["score"]))
            self.e_score_row.set_sensitive(True)
        else:
            self.e_unrated_row.set_active(True)
            self.e_score_row.set_sensitive(False)

        # Progress
        if self._edit_kind == "anime":
            self.e_progress_row.set_visible(True)
            self.e_progress_row.set_text(data.get("progress", ""))
        else:
            self.e_progress_row.set_visible(False)

        # Note
        self.e_note_row.set_text(data.get("note", ""))

        # Review
        has = data["has_review"]
        self.e_review_switch_row.set_active(has)
        self.e_review_view.set_sensitive(has)
        self.e_review_buffer.set_text(data.get("review_text", ""))

        self.e_form_box.set_visible(True)

    def _clear_edit_form(self):
        self._edit_selected_entry = None
        self._edit_had_review = False
        self.e_form_box.set_visible(False)
        self.e_title_row.set_subtitle("")
        self.e_image_row.set_subtitle("")
        self.e_subtype_entry_row.set_text("")
        self.e_subtype_combo_row.set_selected(0)
        self.e_score_row.set_value(8)
        self.e_unrated_row.set_active(False)
        self.e_progress_row.set_text("")
        self.e_note_row.set_text("")
        self.e_review_switch_row.set_active(False)
        self.e_review_buffer.set_text("")
        self.e_search_entry.set_text("")

    def _on_edit_unrated_toggled(self, *_):
        self.e_score_row.set_sensitive(not self.e_unrated_row.get_active())

    def _on_edit_review_toggled(self, *_):
        active = self.e_review_switch_row.get_active()
        self.e_review_view.set_sensitive(active)
        if active:
            self.e_review_view.grab_focus()

    def _on_save_clicked(self, *_):
        try:
            self._save_edit()
        except Exception as e:
            self._toast(f"✗ {e}", error=True)

    def _save_edit(self):
        if not self.project_path:
            raise ValueError("Select a project folder first")
        if not self._edit_selected_entry:
            raise ValueError("No entry selected")

        title = self._edit_selected_entry["title"]

        if self._edit_kind == "anime":
            subtype = ANIME_SUBTYPES[self.e_subtype_combo_row.get_selected()]
        else:
            subtype = self.e_subtype_entry_row.get_text().strip()
            if not subtype:
                raise ValueError("Subtype is required")

        statuses = ANIME_STATUSES if self._edit_kind == "anime" else GAME_STATUSES
        status_label, status_key = statuses[self.e_status_row.get_selected()]

        score = None
        if not self.e_unrated_row.get_active():
            score = int(self.e_score_row.get_value())

        updates = {
            "subtype": subtype,
            "status_label": status_label,
            "status_key": status_key,
            "score": score,
            "note": self.e_note_row.get_text().strip(),
        }
        if self._edit_kind == "anime":
            updates["progress"] = self.e_progress_row.get_text().strip()

        review_text = None
        if self.e_review_switch_row.get_active():
            start = self.e_review_buffer.get_start_iter()
            end = self.e_review_buffer.get_end_iter()
            review_text = self.e_review_buffer.get_text(start, end, False).strip()
            if not review_text:
                raise ValueError("Review is enabled but text is empty")

        result = archive_logic.edit_entry(
            self.project_path, self._edit_kind, title, updates, review_text
        )

        msg = f"✓ Updated '{title}'"
        if result["has_review_now"] and not result["had_review"]:
            msg += f"  +  /reviews/{self._edit_kind}/{result['slug']}"
        elif not result["has_review_now"] and result["had_review"]:
            msg += "  ·  review removed"
        self._toast(msg)

        # Refresh the cache and reload the form with the updated values
        self._edit_entries_cache = []
        self._reload_edit_entries()
        try:
            self._load_entry_into_form(title)
        except Exception:
            self._clear_edit_form()
