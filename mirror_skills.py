#!/usr/bin/env python3
"""Mirror Claude Code skills into other agent CLIs (Codex, Gemini CLI, Qwen Code).

A skill is a directory holding SKILL.md plus whatever it references. Three of the
CLIs that read skills disagree about *where* they look and *what* frontmatter they
tolerate, so "just copy the folder" fails in two different ways:

  * codex rejects the whole SKILL.md when it meets a frontmatter key it does not
    know ("Unexpected key(s) in SKILL.md frontmatter"), so a Claude skill carrying
    an extra key silently stops existing on that side.
  * Gemini CLI and Qwen Code accept the frontmatter as-is, so they do not need a
    copy at all -- a symlink (junction on Windows) keeps one source of truth.

Both are handled here per destination. Deletion is scoped: only directories this
script created are ever removed, so a skill you placed in the destination by hand
survives every run.

    python mirror_skills.py --dest gemini            # link every canon skill
    python mirror_skills.py --dest codex --skills code-master,task-master
    python mirror_skills.py --dest all --check       # drift check, exit 1 if stale

Standard library only. Tested on Linux, macOS and Windows.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

CANON_DEFAULT = Path.home() / ".claude" / "skills"

# Written into copied skills so pruning can tell "we made this" from "the user put
# this here". Linked skills need no marker: the link target is the proof.
MARKER = ".mirrored-from-claude"
MARKER_TEXT = (
    "This directory was copied from the Claude skills canon by mirror_skills.py.\n"
    "Edits here are overwritten on the next run -- change the canon instead.\n"
)

SKIP_SUFFIXES = {".bak", ".pyc"}
SKIP_DIRS = {"__pycache__", ".git"}
FM_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):")

# strategy: "link" keeps a single source of truth; "copy" is only for destinations
# that need the frontmatter filtered. allowed_keys=None means "take it as it is".
DESTINATIONS = {
    "codex": {
        "root": lambda: Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills",
        "strategy": "copy",
        # Must match the implementation's own allow-list, or the skill fails to load.
        "allowed_keys": {"name", "description", "license", "allowed-tools", "metadata"},
    },
    "gemini": {
        "root": lambda: Path.home() / ".gemini" / "skills",
        "strategy": "link",
        "allowed_keys": None,
    },
    "qwen": {
        "root": lambda: Path.home() / ".qwen" / "skills",
        "strategy": "link",
        "allowed_keys": None,
    },
}


class MirrorError(Exception):
    pass


# --- canon -----------------------------------------------------------------------

def canon_skills(canon: Path) -> dict[str, Path]:
    """Every directory directly under the canon that actually is a skill."""
    if not canon.is_dir():
        raise MirrorError(f"canon not found: {canon}")
    return {p.name: p for p in sorted(canon.iterdir())
            if p.is_dir() and (p / "SKILL.md").is_file()}


def select(canon: Path, names: str | None) -> dict[str, Path]:
    found = canon_skills(canon)
    if not names:
        return found
    picked = {}
    for name in [n.strip() for n in names.split(",") if n.strip()]:
        if name not in found:
            raise MirrorError(f"no such skill in canon: {name} (have: {', '.join(found) or 'none'})")
        picked[name] = found[name]
    return picked


# --- frontmatter -----------------------------------------------------------------

def sanitize_frontmatter(name: str, text: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Drop frontmatter keys the destination does not know. Returns (text, dropped).

    Line-based on purpose: a YAML round-trip would reformat the block, and these
    files are read by humans too. Lines belonging to a kept key (nested values,
    list items) travel with it because `key` only changes on a new top-level key.
    """
    if not text.startswith("---"):
        raise MirrorError(f"{name}/SKILL.md does not start with frontmatter")
    end = text.find("\n---", 3)
    if end < 0:
        raise MirrorError(f"{name}/SKILL.md has an unclosed frontmatter block")
    head, rest = text[3:end], text[end:]

    kept: list[str] = []
    dropped: list[str] = []
    key: str | None = None
    for line in head.splitlines():
        match = FM_KEY_RE.match(line)
        if match:
            key = match.group(1)
        if key is None or key in allowed:
            kept.append(line)
        elif match:
            dropped.append(key)

    body = "\n".join(kept)
    for required in ("name", "description"):
        if not re.search(rf"^{required}:\s*\S", body, re.M):
            raise MirrorError(f"{name}/SKILL.md: `{required}` is empty or missing after filtering")
    return "---" + body + rest, dropped


# --- link / copy -----------------------------------------------------------------

def link_dir(src: Path, dst: Path) -> str:
    """Symlink, falling back to a Windows junction. Returns the method used.

    Windows refuses symlinks without Developer Mode or elevation, but junctions to
    a local directory need neither -- which is why the fallback exists rather than
    telling the user to run as administrator.
    """
    try:
        os.symlink(src, dst, target_is_directory=True)
        return "symlink"
    except OSError:
        if os.name != "nt":
            raise
        import _winapi  # stdlib, present on every CPython for Windows
        _winapi.CreateJunction(str(src), str(dst))
        return "junction"


def is_link(path: Path) -> bool:
    """Symlink, or -- on Windows -- a junction. os.path.isjunction landed in 3.12;
    older runtimes simply see junctions as ordinary directories, which is safe here
    because it only makes pruning more conservative."""
    if path.is_symlink():
        return True
    return getattr(os.path, "isjunction", lambda _p: False)(path)


def links_to_canon(path: Path, canon: Path) -> bool:
    """True when this entry is a link we own -- it resolves inside the canon."""
    try:
        return is_link(path) and canon.resolve() in path.resolve().parents
    except OSError:
        return False


def copy_skill(name: str, src: Path, dst: Path, allowed: set[str] | None) -> list[str]:
    """Copy a whole skill directory, filtering SKILL.md frontmatter. Returns dropped keys.

    The entire directory travels, not just SKILL.md: relative references inside a
    skill resolve against the directory it was loaded from, so mirroring the entry
    point alone leaves it pointing at files that are not there.
    """
    dropped: list[str] = []
    for path in sorted(src.rglob("*")):
        if not path.is_file() or path.suffix in SKIP_SUFFIXES or SKIP_DIRS & set(path.parts):
            continue
        rel = path.relative_to(src)
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            out.write_bytes(data)          # binary asset: byte-for-byte
            continue
        if rel.as_posix() == "SKILL.md" and allowed is not None:
            text, keys = sanitize_frontmatter(name, text, allowed)
            dropped += keys
        out.write_text(text, encoding="utf-8", newline="\n")
    (dst / MARKER).write_text(MARKER_TEXT, encoding="utf-8", newline="\n")
    return dropped


def is_ours(path: Path, canon: Path) -> bool:
    return links_to_canon(path, canon) or (path / MARKER).is_file()


def remove(path: Path) -> None:
    """Delete a link without following it, or a real directory with its contents."""
    if is_link(path):
        os.rmdir(path) if os.name == "nt" else path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


# --- destinations ----------------------------------------------------------------

def install(dest: str, canon: Path, picked: dict[str, Path], check: bool) -> tuple[int, list[str]]:
    """Bring one destination in line with the canon. Returns (changes, notes)."""
    spec = DESTINATIONS[dest]
    root = spec["root"]()
    notes: list[str] = []
    changes = 0

    for name, src in picked.items():
        dst = root / name
        if spec["strategy"] == "link":
            if links_to_canon(dst, canon):
                continue
            if check:
                notes.append(f"{dest}: {name} is not linked to the canon")
                changes += 1
                continue
            root.mkdir(parents=True, exist_ok=True)
            if dst.exists() or dst.is_symlink():
                if not is_ours(dst, canon):
                    raise MirrorError(
                        f"{dst} exists and was not created by this script -- "
                        f"move it aside first, it will never be deleted automatically")
                remove(dst)
            how = link_dir(src, dst)
            notes.append(f"{dest}: linked {name} ({how})")
            changes += 1
        else:
            if check:
                if not dst.is_dir():
                    notes.append(f"{dest}: {name} is missing")
                    changes += 1
                elif not (dst / MARKER).is_file():
                    notes.append(f"{dest}: {name} exists but is not a mirror (left alone)")
                continue
            if dst.exists() and not is_ours(dst, canon):
                raise MirrorError(
                    f"{dst} exists and was not created by this script -- "
                    f"move it aside first, it will never be deleted automatically")
            if dst.exists():
                remove(dst)
            dropped = copy_skill(name, src, dst, spec["allowed_keys"])
            notes.append(f"{dest}: copied {name}"
                         + (f" (dropped frontmatter: {', '.join(sorted(set(dropped)))})" if dropped else ""))
            changes += 1

    # Pruning is scoped to entries we own. Anything else in the destination is the
    # user's and is reported, never removed.
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            if entry.name in picked or not is_ours(entry, canon):
                continue
            changes += 1
            if check:
                notes.append(f"{dest}: {entry.name} is a stale mirror")
            else:
                remove(entry)
                notes.append(f"{dest}: pruned {entry.name}")
    return changes, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", default="all",
                    help=f"destination: all, or one of {', '.join(DESTINATIONS)}")
    ap.add_argument("--canon", type=Path, default=CANON_DEFAULT,
                    help=f"skills directory to mirror from (default: {CANON_DEFAULT})")
    ap.add_argument("--skills", help="comma-separated skill names (default: every skill in canon)")
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit 1 instead of writing anything")
    args = ap.parse_args()

    dests = list(DESTINATIONS) if args.dest == "all" else [args.dest]
    unknown = [d for d in dests if d not in DESTINATIONS]
    if unknown:
        print(f"unknown destination(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    try:
        picked = select(args.canon, args.skills)
        if not picked:
            print(f"no skills found in {args.canon}", file=sys.stderr)
            return 2
        total = 0
        for dest in dests:
            changes, notes = install(dest, args.canon, picked, args.check)
            total += changes
            for note in notes:
                print(note)
    except MirrorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.check:
        print(f"check: {total} difference(s) from the canon")
        return 1 if total else 0
    print(f"mirrored {len(picked)} skill(s) to {', '.join(dests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
