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
    """Python str -> body of a JSX backtick template literal."""
    s = s.replace("\\", "\\\\")
    s = s.replace("`", "\\`")
    s = s.replace("${", "\\${")
    return s


def _unescape_js_string(s: str) -> str:
    """Reverse of js_string for reading existing entries."""
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n":   out.append("\n")
            elif nxt == "r": out.append("\r")
            elif nxt == "t": out.append("\t")
            else:            out.append(nxt)
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _unescape_jsx_template(s: str) -> str:
    """Reverse of jsx_template for reading existing review paragraphs."""
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "`":   out.append("`")
            elif nxt == "$": out.append("$")
            elif nxt == "\\": out.append("\\")
            else:
                out.append(s[i])
                out.append(nxt)
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


# ============================================================
# JS data-file parsing & editing
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


def _scan_string_literal(content: str, start: int) -> int:
    """Scan past a JS string starting at `start` (pointing at the quote).
    Returns the index AFTER the closing quote."""
    quote = content[start]
    i = start + 1
    while i < len(content):
        if content[i] == "\\":
            i += 2
            continue
        if content[i] == quote:
            return i + 1
        i += 1
    return i


def _scan_entry_block(content: str, start: int) -> int:
    """Given start pointing at `{`, return index AFTER matching `}`."""
    depth = 1
    i = start + 1
    while i < len(content) and depth > 0:
        ch = content[i]
        if ch in ("'", '"', "`"):
            i = _scan_string_literal(content, i)
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def parse_entry_fields(block: str) -> dict:
    """Extract field/value pairs from a single `{...}` entry block."""
    fields = {}
    for raw_line in block.splitlines():
        line = raw_line.strip().rstrip(",")
        if ":" not in line or line.startswith("//"):
            continue
        key_part, _, value_part = line.partition(":")
        key = key_part.strip()
        value_part = value_part.strip()
        if not value_part:
            continue

        if value_part[0] in ("'", '"', "`"):
            quote = value_part[0]
            i = 1
            chars = []
            while i < len(value_part):
                if value_part[i] == "\\" and i + 1 < len(value_part):
                    chars.append(value_part[i] + value_part[i + 1])
                    i += 2
                elif value_part[i] == quote:
                    break
                else:
                    chars.append(value_part[i])
                    i += 1
            fields[key] = _unescape_js_string("".join(chars))
        else:
            m = re.match(r"-?\d+(?:\.\d+)?", value_part)
            if m:
                v = m.group(0)
                fields[key] = float(v) if "." in v else int(v)
    return fields


def parse_data_entries(content: str, array_name: str) -> list:
    """Parse all entries in `export const <array_name> = [...]`.

    Returns a list of dicts with all field values plus internal markers:
      _line_start: start of the line containing the entry's `{`
      _block_end:  end of the entry's `}`
      _full_end:   index just past the trailing `,` (if any)
    """
    pat = re.compile(rf"export\s+const\s+{re.escape(array_name)}\s*=\s*\[")
    m = pat.search(content)
    if not m:
        return []

    end_idx = find_array_close(content, array_name)
    i = m.end()
    entries = []

    while i < end_idx:
        ch = content[i]
        if ch.isspace() or ch == ",":
            i += 1
            continue
        if ch == "/" and i + 1 < end_idx and content[i + 1] == "/":
            while i < end_idx and content[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < end_idx and content[i + 1] == "*":
            i += 2
            while i + 1 < end_idx and not (content[i] == "*" and content[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch != "{":
            i += 1
            continue

        block_start = i
        block_end = _scan_entry_block(content, block_start)
        block = content[block_start:block_end]
        fields = parse_entry_fields(block)

        line_start = block_start
        while line_start > 0 and content[line_start - 1] != "\n":
            line_start -= 1

        full_end = block_end
        if full_end < len(content) and content[full_end] == ",":
            full_end += 1

        entries.append({
            **fields,
            "_line_start": line_start,
            "_block_end": block_end,
            "_full_end": full_end,
        })

        i = full_end

    return entries


def title_exists_in_data(content: str, title: str) -> bool:
    pat = re.compile(r"title:\s*['\"]" + re.escape(title) + r"['\"]")
    return bool(pat.search(content))


def insert_in_array(content: str, array_name: str, entry_text: str) -> str:
    close_idx = find_array_close(content, array_name)
    line_start = close_idx
    while line_start > 0 and content[line_start - 1] != "\n":
        line_start -= 1
    return content[:line_start] + entry_text + "\n" + content[line_start:]


def replace_entry_in_array(content: str, entry: dict, new_entry_text: str) -> str:
    """Replace the entry described by `entry` with `new_entry_text` in place."""
    return content[:entry["_line_start"]] + new_entry_text + content[entry["_full_end"]:]


# ============================================================
# Entry / review JSX builders
# ============================================================

def build_entry(kind: str, fields: dict, review_path=None) -> str:
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


def read_review_paragraphs(review_file: Path) -> str:
    """Read existing review JSX, extract paragraphs as plain text with blank
    lines between them. Used to repopulate the textbox in edit mode.

    Handles both formats:
      - tool-generated: <p>{`text`}</p>  (template literals)
      - hand-written:   <p>text</p>      (plain JSX)
    """
    content = review_file.read_text(encoding="utf-8")

    # Try template-literal format first
    tl_pat = re.compile(r"<p>\{`(.*?)`\}</p>", re.DOTALL)
    matches = tl_pat.findall(content)
    if matches:
        paragraphs = [_unescape_jsx_template(m).strip() for m in matches]
        return "\n\n".join(p for p in paragraphs if p)

    # Fall back to plain <p>text</p>. JSX collapses interior whitespace when
    # rendering, so we do the same here to recover the original prose.
    plain_pat = re.compile(r"<p>(.*?)</p>", re.DOTALL)
    paragraphs = []
    for m in plain_pat.findall(content):
        text = re.sub(r"\s+", " ", m).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


# ============================================================
# App.jsx editing
# ============================================================

def insert_after_import_section(content: str, header: str, new_line: str) -> str:
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
        if stripped.startswith("</Route>") or stripped.startswith("</Routes>"):
            break
        if stripped == "":
            j += 1
            continue
        if stripped.startswith("{/*") or stripped.startswith("//"):
            break
        j += 1

    lines.insert(last_route_idx + 1, new_line + "\n")
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


def remove_review_from_app_jsx(project_dir: Path, kind: str, slug: str):
    """Strip the import and route lines for a review out of App.jsx."""
    app_path = project_dir / "src" / "App.jsx"
    content = app_path.read_text(encoding="utf-8")
    component_name = pascal_case(slug) + "Review"

    import_pat = f"import {component_name} from './pages/reviews/{kind}/{slug}'"
    route_pat = f'path="/reviews/{kind}/{slug}"'

    new_lines = []
    for line in content.splitlines(keepends=True):
        if import_pat in line:
            continue
        if route_pat in line and "<Route" in line:
            continue
        new_lines.append(line)
    app_path.write_text("".join(new_lines), encoding="utf-8")


# ============================================================
# High-level operations
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


def array_name_for(kind: str) -> str:
    return "animeEntries" if kind == "anime" else "gameEntries"


def list_entries(project_dir, kind: str) -> list:
    """Read all entries from the data file for the given kind."""
    project_dir = Path(project_dir).expanduser().resolve()
    validate_project(project_dir)
    data_file = project_dir / "src" / "data" / f"{kind}.js"
    content = data_file.read_text(encoding="utf-8")
    entries = parse_data_entries(content, array_name_for(kind))
    return [{k: v for k, v in e.items() if not k.startswith("_")} for e in entries]


def load_entry_for_edit(project_dir, kind: str, title: str) -> dict:
    """Load one entry plus its existing review text (if any)."""
    project_dir = Path(project_dir).expanduser().resolve()
    validate_project(project_dir)

    data_file = project_dir / "src" / "data" / f"{kind}.js"
    content = data_file.read_text(encoding="utf-8")
    entries = parse_data_entries(content, array_name_for(kind))
    target = next((e for e in entries if e.get("title") == title), None)
    if target is None:
        raise ValueError(f"Entry '{title}' not found in {kind}.js")

    slug = slugify(title)
    review_file = project_dir / "src" / "pages" / "reviews" / kind / f"{slug}.jsx"
    review_text = ""
    if review_file.exists():
        review_text = read_review_paragraphs(review_file)

    result = {k: v for k, v in target.items() if not k.startswith("_")}
    result["slug"] = slug
    result["review_text"] = review_text
    result["has_review"] = review_file.exists()
    return result


def add_entry(project_dir, kind: str, fields: dict, review_text=None) -> dict:
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
        review_file = project_dir / "src" / "pages" / "reviews" / kind / f"{slug}.jsx"
        if review_file.exists():
            raise ValueError(f"Review file already exists: {review_file}")

    entry_text = build_entry(kind, fields, review_path)

    data_file = project_dir / "src" / "data" / f"{kind}.js"
    data_content = data_file.read_text(encoding="utf-8")
    if title_exists_in_data(data_content, fields["title"]):
        raise ValueError(f"`{fields['title']}` already exists in {kind}.js")

    new_data_content = insert_in_array(data_content, array_name_for(kind), entry_text)

    review_jsx = build_review_jsx(component, kind, fields) if review_text is not None else None

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


def edit_entry(project_dir, kind: str, title: str, updates: dict, review_text) -> dict:
    """Update an existing entry. Title and image are NOT changed.

    updates keys: subtype, status_label, status_key, score, progress (anime), note
    review_text: non-empty string -> create/overwrite review; empty/None -> remove
    """
    project_dir = Path(project_dir).expanduser().resolve()
    validate_project(project_dir)

    data_file = project_dir / "src" / "data" / f"{kind}.js"
    content = data_file.read_text(encoding="utf-8")
    entries = parse_data_entries(content, array_name_for(kind))
    target = next((e for e in entries if e.get("title") == title), None)
    if target is None:
        raise ValueError(f"Entry '{title}' not found in {kind}.js")

    slug = slugify(title)
    component = pascal_case(slug) + "Review"
    review_file = project_dir / "src" / "pages" / "reviews" / kind / f"{slug}.jsx"

    had_review = target.get("reviewPath") is not None or review_file.exists()
    new_text = (review_text or "").strip()
    will_have_review = bool(new_text)

    new_fields = {
        "title": target["title"],
        "subtype": updates.get("subtype", target.get("type", "")),
        "status_label": updates["status_label"],
        "status_key": updates["status_key"],
        "score": updates.get("score"),
        "image_path": target["image"],
        "note": updates.get("note", ""),
    }
    if kind == "anime":
        new_fields["progress"] = updates.get("progress", target.get("progress", ""))

    review_path = f"/reviews/{kind}/{slug}" if will_have_review else None
    new_entry_text = build_entry(kind, new_fields, review_path)
    new_data_content = replace_entry_in_array(content, target, new_entry_text)

    review_jsx = None
    if will_have_review:
        new_fields["review_text"] = new_text
        review_jsx = build_review_jsx(component, kind, new_fields)

    # Commit phase
    data_file.write_text(new_data_content, encoding="utf-8")

    if will_have_review:
        review_file.parent.mkdir(parents=True, exist_ok=True)
        review_file.write_text(review_jsx, encoding="utf-8")
        if not had_review:
            try:
                update_app_jsx(project_dir, kind, slug, component)
            except ValueError as e:
                if "already registered" not in str(e):
                    raise
    else:
        if review_file.exists():
            review_file.unlink()
        if had_review:
            remove_review_from_app_jsx(project_dir, kind, slug)

    return {
        "slug": slug,
        "had_review": had_review,
        "has_review_now": will_have_review,
        "review_file": str(review_file) if will_have_review else None,
    }
