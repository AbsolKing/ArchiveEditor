"""
File-editing logic for the absolking-archive project.

Pure Python — no GUI imports. Used by the GTK window for actual file IO.
"""

import re
import shutil
from pathlib import Path


# ============================================================
# Slug & string helpers
# ============================================================

def slugify(text: str) -> str:
    """'Angel Beats!' -> 'angel-beats'."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def pascal_case(slug: str) -> str:
    """'angel-beats' -> 'AngelBeats'."""
    return "".join(p.capitalize() for p in slug.split("-") if p)


def js_string(s: str) -> str:
    """Python str -> single-quoted JS string with escapes."""
    s = s.replace("\\", "\\\\")
    s = s.replace("'", "\\'")
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    return f"'{s}'"


def jsx_template(s: str) -> str:
    """Python str -> body of a JSX backtick template literal (escaping inserted)."""
    s = s.replace("\\", "\\\\")
    s = s.replace("`", "\\`")
    s = s.replace("${", "\\${")
    return s


# ============================================================
# JS data-file editing
# ============================================================

def find_array_close(content: str, array_name: str) -> int:
    """Find the index of the `]` that closes `export const <name> = [...]`."""
    pat = re.compile(rf"export\s+const\s+{re.escape(array_name)}\s*=\s*\[")
    m = pat.search(content)
    if not m:
        raise ValueError(f"Array `{array_name}` not found in data file")

    pos = m.end()
    depth = 1
    while pos < len(content):
        ch = content[pos]
        if ch in ("'", '"', "`"):
            quote = ch
            pos += 1
            while pos < len(content):
                if content[pos] == "\\":
                    pos += 2
                    continue
                if content[pos] == quote:
                    pos += 1
                    break
                pos += 1
            continue
        if ch == "/" and pos + 1 < len(content) and content[pos + 1] == "/":
            while pos < len(content) and content[pos] != "\n":
                pos += 1
            continue
        if ch == "/" and pos + 1 < len(content) and content[pos + 1] == "*":
            pos += 2
            while pos + 1 < len(content):
                if content[pos] == "*" and content[pos + 1] == "/":
                    pos += 2
                    break
                pos += 1
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    raise ValueError(f"Unmatched `[` in array `{array_name}`")


def insert_in_array(content: str, array_name: str, entry_text: str) -> str:
    close_idx = find_array_close(content, array_name)
    line_start = close_idx
    while line_start > 0 and content[line_start - 1] != "\n":
        line_start -= 1
    return content[:line_start] + entry_text + "\n" + content[line_start:]


def title_exists_in_data(content: str, title: str) -> bool:
    pat = re.compile(r"title:\s*['\"]" + re.escape(title) + r"['\"]")
    return bool(pat.search(content))


# ============================================================
# Entry / review JSX builders
# ============================================================

def build_entry(kind: str, fields: dict, review_path: str | None = None) -> str:
    parts = [
        f"    title: {js_string(fields['title'])},",
        f"    type: {js_string(fields['subtype'])},",
        f"    status: {js_string(fields['status_label'])},",
        f"    statusKey: {js_string(fields['status_key'])},",
    ]
    if fields.get("score") is not None:
        parts.append(f"    score: {fields['score']},")
    if kind == "anime" and fields.get("progress"):
        parts.append(f"    progress: {js_string(fields['progress'])},")
    parts.append(f"    image: {js_string(fields['image_path'])},")
    parts.append(f"    note: {js_string(fields.get('note', ''))},")
    if review_path:
        parts.append(f"    reviewPath: {js_string(review_path)},")
    return "  {\n" + "\n".join(parts) + "\n  },"


def build_review_jsx(component_name: str, kind: str, fields: dict) -> str:
    category = "Anime" if kind == "anime" else "Games"
    category_path = f"/database/{kind}"

    raw = fields["review_text"].strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    if not paragraphs:
        paragraphs = ["Review coming soon."]
    body = "\n      ".join(f"<p>{{`{jsx_template(p)}`}}</p>" for p in paragraphs)

    title_attr = f"title={{`{jsx_template(fields['title'])}`}}"
    cover_attr = f"cover={{`{jsx_template(fields['image_path'])}`}}"
    score_line = ""
    if fields.get("score") is not None:
        score_line = f"\n      score={{{fields['score']}}}"

    return (
        "import ReviewLayout from '../../../components/reviews/ReviewLayout'\n"
        "\n"
        f"export default function {component_name}() {{\n"
        "  return (\n"
        "    <ReviewLayout\n"
        f"      {title_attr}{score_line}\n"
        f'      category="{category}"\n'
        f'      categoryPath="{category_path}"\n'
        f"      {cover_attr}\n"
        "    >\n"
        f"      {body}\n"
        "    </ReviewLayout>\n"
        "  )\n"
        "}\n"
    )


# ============================================================
# App.jsx editing
# ============================================================

def insert_after_import_section(content: str, header: str, new_line: str) -> str:
    """Insert an import line inside a labelled App.jsx import section.

    The previous implementation searched for the next blank line. That was
    fragile when the section had no blank separator or when formatters changed
    whitespace. This version inserts after the existing import lines that follow
    the section marker.
    """
    lines = content.splitlines(keepends=True)
    marker_idx = None
    for i, line in enumerate(lines):
        if header in line:
            marker_idx = i
            break
    if marker_idx is None:
        raise ValueError(f"Section header `{header}` not found in App.jsx")

    j = marker_idx + 1
    while j < len(lines) and lines[j].lstrip().startswith("import "):
        j += 1

    lines.insert(j, new_line + "\n")
    return "".join(lines)


def insert_after_route_section(content: str, header: str, new_line: str) -> str:
    """Insert a <Route> inside a labelled review section in App.jsx.

    This intentionally inserts before the parent </Route>, never after the end
    of the App() component. It handles sections with one or many review routes
    and does not depend on blank lines.
    """
    lines = content.splitlines(keepends=True)
    marker_idx = None
    for i, line in enumerate(lines):
        if header in line:
            marker_idx = i
            break
    if marker_idx is None:
        raise ValueError(f"Route section `{header}` not found in App.jsx")

    j = marker_idx + 1
    last_route_idx = marker_idx
    while j < len(lines):
        stripped = lines[j].strip()
        if stripped.startswith("<Route "):
            last_route_idx = j
            j += 1
            continue
        # Stop before the layout route closes or the Routes block ends.
        if stripped.startswith("</Route>") or stripped.startswith("</Routes>"):
            break
        # Skip empty lines between review routes, but don't use them as the
        # insertion target.
        if stripped == "":
            j += 1
            continue
        # A different comment/section starts; insert before it.
        if stripped.startswith("{/*") or stripped.startswith("//"):
            break
        j += 1

    insert_idx = last_route_idx + 1
    lines.insert(insert_idx, new_line + "\n")
    return "".join(lines)


def update_app_jsx(project_dir: Path, kind: str, slug: str, component_name: str):
    app_path = project_dir / "src" / "App.jsx"
    content = app_path.read_text(encoding="utf-8")

    import_line = f"import {component_name} from './pages/reviews/{kind}/{slug}'"
    route_line = f'        <Route path="/reviews/{kind}/{slug}" element={{<{component_name} />}} />'

    if import_line in content:
        raise ValueError(f"Review for `{slug}` is already registered in App.jsx")

    if kind == "anime":
        import_header = "// ── Anime reviews ──"
        route_header = "{/* Anime reviews */}"
    else:
        import_header = "// ── Game reviews ──"
        route_header = "{/* Game reviews */}"

    content = insert_after_import_section(content, import_header, import_line)
    content = insert_after_route_section(content, route_header, route_line)
    app_path.write_text(content, encoding="utf-8")


# ============================================================
# High-level operation
# ============================================================

def validate_project(project_dir: Path):
    must_exist = [
        project_dir / "src" / "App.jsx",
        project_dir / "src" / "data" / "anime.js",
        project_dir / "src" / "data" / "games.js",
        project_dir / "public" / "covers",
    ]
    for p in must_exist:
        if not p.exists():
            raise ValueError(
                "Doesn't look like the archive project.\n"
                f"Missing: {p}"
            )


def add_entry(project_dir, kind: str, fields: dict, review_text: str | None = None) -> dict:
    project_dir = Path(project_dir).expanduser().resolve()
    validate_project(project_dir)

    slug = slugify(fields["title"])
    if not slug:
        raise ValueError("Title produces an empty slug")
    component = pascal_case(slug) + "Review"

    image_filename = fields["image_filename"]
    image_dest = project_dir / "public" / "covers" / kind / image_filename
    image_source = fields.get("image_source")
    if image_source:
        src = Path(image_source)
        if not src.exists():
            raise ValueError(f"Image source not found: {src}")
        image_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, image_dest)

    fields["image_path"] = f"/covers/{kind}/{image_filename}"

    review_path = None
    review_file = None
    if review_text is not None:
        review_path = f"/reviews/{kind}/{slug}"
        fields["review_text"] = review_text
        review_file = (
            project_dir / "src" / "pages" / "reviews" / kind / f"{slug}.jsx"
        )
        if review_file.exists():
            raise ValueError(f"Review file already exists: {review_file}")

    entry_text = build_entry(kind, fields, review_path)

    data_file = project_dir / "src" / "data" / f"{kind}.js"
    data_content = data_file.read_text(encoding="utf-8")
    if title_exists_in_data(data_content, fields["title"]):
        raise ValueError(f"`{fields['title']}` already exists in {kind}.js")

    array_name = "animeEntries" if kind == "anime" else "gameEntries"
    new_data_content = insert_in_array(data_content, array_name, entry_text)

    review_jsx = None
    if review_text is not None:
        review_jsx = build_review_jsx(component, kind, fields)

    # Commit phase — writes only happen after every check passed
    data_file.write_text(new_data_content, encoding="utf-8")
    if review_text is not None:
        review_file.parent.mkdir(parents=True, exist_ok=True)
        review_file.write_text(review_jsx, encoding="utf-8")
        update_app_jsx(project_dir, kind, slug, component)

    return {
        "slug": slug,
        "component": component,
        "review_file": str(review_file) if review_file else None,
        "image_dest": str(image_dest) if image_source else None,
        "data_file": str(data_file),
    }
