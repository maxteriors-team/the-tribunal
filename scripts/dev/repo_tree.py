#!/usr/bin/env python3
"""Render the repo's directory tree as text or HTML, optionally over HTTP.

Examples::

    # Print the directory tree (per-directory file counts) to stdout.
    python scripts/dev/repo_tree.py

    # Show every tracked file, not just directories.
    python scripts/dev/repo_tree.py --files

    # Limit how deep the tree descends.
    python scripts/dev/repo_tree.py --depth 3

    # Restrict to a subtree.
    python scripts/dev/repo_tree.py backend/app/services

    # Write an HTML page to stdout.
    python scripts/dev/repo_tree.py --html > tree.html

    # Serve the HTML on a local HTTP server for browser preview.
    python scripts/dev/repo_tree.py --serve
    python scripts/dev/repo_tree.py --serve --port 9000 --no-open
"""

from __future__ import annotations

import argparse
import html
import http.server
import socket
import subprocess
import sys
import threading
import webbrowser
from collections import defaultdict
from pathlib import Path

# This file lives at ``scripts/dev/repo_tree.py``; the repo root is two
# directories up.
REPO_ROOT = Path(__file__).resolve().parents[2]

# The server always binds loopback (127.0.0.1) so the preview stays local.
HOST = "127.0.0.1"


class TreeError(RuntimeError):
    """Raised when the tree cannot be built (e.g. not a git checkout)."""


def list_tracked_files(root: Path, subpath: str | None) -> list[str]:
    """Return git-tracked files (relative to ``root``), optionally scoped."""

    cmd = ["git", "ls-files"]
    if subpath:
        cmd.append("--")
        cmd.append(subpath)
    try:
        result = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:  # git not installed
        raise TreeError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise TreeError(
            f"git ls-files failed (is {root} a git checkout?): {exc.stderr.strip()}"
        ) from exc

    files = [line for line in result.stdout.splitlines() if line]
    if not files:
        scope = f" under {subpath!r}" if subpath else ""
        raise TreeError(f"no tracked files found{scope}")
    return files


class Node:
    """A directory in the tree, holding child dirs and a direct-file count."""

    __slots__ = ("name", "dirs", "files", "direct_files")

    def __init__(self, name: str) -> None:
        self.name = name
        self.dirs: dict[str, Node] = {}
        self.files: list[str] = []  # direct child file names (leaf entries)
        self.direct_files = 0

    def child(self, name: str) -> "Node":
        node = self.dirs.get(name)
        if node is None:
            node = Node(name)
            self.dirs[name] = node
        return node


def build_tree(files: list[str], root_label: str) -> Node:
    """Build a Node tree from a flat list of ``a/b/c.py`` paths."""

    root = Node(root_label)
    for path in files:
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            node = node.child(part)
        node.files.append(parts[-1])
        node.direct_files += 1
    return root


def _sorted_dirs(node: Node) -> list[Node]:
    return [node.dirs[k] for k in sorted(node.dirs, key=str.lower)]


def render_text(
    root: Node,
    *,
    show_files: bool,
    max_depth: int | None,
) -> str:
    """Render the tree as an ASCII/Unicode connector tree."""

    lines: list[str] = [f"{root.name}/  ({root.direct_files} root files)"]

    def walk(node: Node, prefix: str, depth: int) -> None:
        if max_depth is not None and depth >= max_depth:
            return
        dirs = _sorted_dirs(node)
        files = sorted(node.files, key=str.lower) if show_files else []
        entries: list[tuple[str, Node | None]] = [(d.name, d) for d in dirs]
        entries += [(f, None) for f in files]

        for i, (name, child) in enumerate(entries):
            last = i == len(entries) - 1
            conn = "└── " if last else "├── "
            if child is not None:
                count = child.direct_files
                suffix = f"  ({count} files)" if count and not show_files else ""
                lines.append(f"{prefix}{conn}{name}/{suffix}")
                ext = "    " if last else "│   "
                walk(child, prefix + ext, depth + 1)
            else:
                lines.append(f"{prefix}{conn}{name}")

    walk(root, "", 0)
    return "\n".join(lines)


def render_html(
    root: Node,
    *,
    show_files: bool,
    max_depth: int | None,
    title: str,
) -> str:
    """Render the tree as a standalone, self-contained HTML page."""

    total_dirs = 0
    total_files = 0

    def count(node: Node) -> None:
        nonlocal total_dirs, total_files
        total_files += node.direct_files
        for child in node.dirs.values():
            total_dirs += 1
            count(child)

    count(root)

    items: list[str] = []

    def walk(node: Node, depth: int) -> None:
        if max_depth is not None and depth >= max_depth:
            return
        for child in _sorted_dirs(node):
            badge = (
                f'<span class="count">{child.direct_files}</span>'
                if child.direct_files
                else ""
            )
            pad = depth * 22
            items.append(
                f'<li style="--pad:{pad}px" class="dir">'
                f'<span class="name">{html.escape(child.name)}/</span>{badge}</li>'
            )
            walk(child, depth + 1)
            if show_files:
                for fname in sorted(child.files, key=str.lower):
                    fpad = (depth + 1) * 22
                    items.append(
                        f'<li style="--pad:{fpad}px" class="file">'
                        f'<span class="name">{html.escape(fname)}</span></li>'
                    )

    if show_files:
        for fname in sorted(root.files, key=str.lower):
            items.append(
                f'<li style="--pad:0px" class="file">'
                f'<span class="name">{html.escape(fname)}</span></li>'
            )
    walk(root, 0)

    rows = "\n".join(items)
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    margin: 0;
    font: 14px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    background: #0d1117;
    color: #e6edf3;
  }}
  header {{
    position: sticky; top: 0;
    padding: 16px 24px;
    background: #161b22;
    border-bottom: 1px solid #30363d;
  }}
  header h1 {{ margin: 0 0 4px; font-size: 16px; }}
  header .meta {{ color: #7d8590; font-size: 12px; }}
  ul {{ list-style: none; margin: 0; padding: 16px 24px; }}
  li {{ padding-left: var(--pad); white-space: nowrap; }}
  li.dir .name {{ color: #58a6ff; font-weight: 600; }}
  li.file .name {{ color: #adbac7; }}
  .count {{
    margin-left: 8px;
    padding: 0 7px;
    border-radius: 10px;
    background: #21262d;
    color: #7d8590;
    font-size: 11px;
  }}
</style>
</head>
<body>
<header>
  <h1>{safe_title}/</h1>
  <div class="meta">{total_dirs} directories &middot; {total_files} files</div>
</header>
<ul>
{rows}
</ul>
</body>
</html>
"""


def _free_port(preferred: int) -> int:
    """Return ``preferred`` if bindable, else an OS-assigned free port."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, preferred))
            return preferred
        except OSError:
            sock.bind((HOST, 0))
            return sock.getsockname()[1]


def serve(page: str, *, port: int, open_browser: bool) -> None:
    """Serve a single HTML page until interrupted."""

    body = page.encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:  # silence per-request noise
            return

    port = _free_port(port)
    server = http.server.HTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}/"
    print(f"Serving repo tree at {url}  (Ctrl-C to stop)", file=sys.stderr)

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    finally:
        server.server_close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the repo directory tree as text or HTML.",
    )
    parser.add_argument(
        "subpath",
        nargs="?",
        help="Optional path to scope the tree (e.g. backend/app/services).",
    )
    parser.add_argument(
        "--files",
        action="store_true",
        help="Include individual files, not just directories.",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=None,
        metavar="N",
        help="Maximum directory depth to display.",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Emit an HTML page instead of plain text.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve the HTML tree over a local HTTP server for browser preview.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8123,
        help="Preferred port when serving (default: 8123; falls back if taken).",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not auto-open the browser when serving.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.depth is not None and args.depth < 1:
        print("error: --depth must be >= 1", file=sys.stderr)
        return 2

    try:
        files = list_tracked_files(REPO_ROOT, args.subpath)
    except TreeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    label = args.subpath.rstrip("/") if args.subpath else REPO_ROOT.name
    if args.subpath:
        # ``git ls-files -- <subpath>`` returns repo-relative paths; strip the
        # prefix so the scoped tree is rooted at the subpath itself.
        prefix = label + "/"
        files = [f[len(prefix):] if f.startswith(prefix) else f for f in files]
    root = build_tree(files, label)

    if args.serve or args.html:
        page = render_html(
            root,
            show_files=args.files,
            max_depth=args.depth,
            title=label,
        )
        if args.serve:
            serve(
                page,
                port=args.port,
                open_browser=not args.no_open,
            )
        else:
            sys.stdout.write(page)
        return 0

    print(render_text(root, show_files=args.files, max_depth=args.depth))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
