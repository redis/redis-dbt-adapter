"""Publish the existing Markdown without copying source files or other repo data."""

import posixpath
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from mkdocs.structure.files import File

ROOT = Path(__file__).resolve().parent.parent


def source_paths(nav):
    """Only explicitly listed navigation pages are included in the public site."""
    for item in nav:
        for value in item.values():
            if isinstance(value, list):
                yield from source_paths(value)
            else:
                yield value


def on_files(files, config):
    for source in source_paths(config.nav):
        files.append(File.generated(config, source, abs_src_path=str(ROOT / source)))
    return files


def on_page_markdown(markdown, page, config, files):
    """Keep doc links local; send code and directory links to their GitHub source."""
    def rewrite_link(match):
        target = urlsplit(match.group(1))
        if target.scheme or target.netloc or not target.path:
            return match.group(0)
        path = posixpath.normpath(posixpath.join(
            posixpath.dirname(page.file.src_uri), unquote(target.path)
        ))
        if files.get_file_from_path(path) is not None:
            return match.group(0)
        source = ROOT / path
        if not source.is_relative_to(ROOT) or not source.exists():
            # Leave invalid links for MkDocs' strict validation to report.
            return match.group(0)
        kind = "tree" if source.is_dir() else "blob"
        url = urlunsplit(("https", "github.com",
                         f"/redis/redis-dbt-adapter/{kind}/main/{quote(path)}",
                         target.query, target.fragment))
        return f"]({url})"

    # Do not rewrite examples inside fenced code blocks.
    sections = re.split(r"(^```[^\n]*\n.*?^```[^\n]*$)", markdown,
                        flags=re.MULTILINE | re.DOTALL)
    for index in range(0, len(sections), 2):
        sections[index] = re.sub(r"\]\(([^\s)]+)\)", rewrite_link, sections[index])
    return "".join(sections)


def on_serve(server, config, builder):
    for source in source_paths(config.nav):
        server.watch(str(ROOT / source))
    return server
