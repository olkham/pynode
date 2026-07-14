"""Install per-node dependencies for an installed PyNode package.

Each node under ``pynode/nodes/<NodeName>/`` may ship a ``requirements.txt``
listing packages it needs. Those files are *not* installed by ``pip install
pynode-flow`` -- pip only reads the dependencies/extras in ``pyproject.toml``.

Most node dependencies are covered by the ``pip install "pynode-flow[full]"``
extra. This command is the escape hatch for the rest: it walks the node folders
of the *installed* package (so it works from a plain ``pip install``, not only a
source checkout) and runs ``pip install -r`` for each node, which is the only
way to pull dependencies that cannot live in ``pyproject.toml`` -- e.g. vendor
SDKs like the Omron/Sentech ``stapipy`` (OmronCameraNode).

Usage::

    pynode-install-nodes                 # install deps for every node
    pynode-install-nodes --node MQTTNode # only the named node(s)
    pynode-install-nodes --list          # show nodes with a requirements.txt
    pynode-install-nodes --dry-run       # print what would be installed
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _nodes_dir() -> Path:
    """Return the ``nodes`` directory that ships inside this package."""
    return Path(__file__).resolve().parent / "nodes"


def _has_real_requirements(requirements_file: Path) -> bool:
    """True if the file lists at least one non-comment, non-blank requirement."""
    try:
        for raw_line in requirements_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#"):
                return True
    except OSError:
        return False
    return False


def find_node_requirements(nodes_dir: Path | None = None) -> list[tuple[str, Path]]:
    """Return ``(node_name, requirements_path)`` for nodes with real requirements."""
    nodes_dir = nodes_dir or _nodes_dir()
    found: list[tuple[str, Path]] = []
    if not nodes_dir.is_dir():
        return found
    for node_dir in sorted(p for p in nodes_dir.iterdir() if p.is_dir()):
        if node_dir.name.startswith("__"):
            continue
        requirements_file = node_dir / "requirements.txt"
        if requirements_file.is_file() and _has_real_requirements(requirements_file):
            found.append((node_dir.name, requirements_file))
    return found


def install_node_requirements(
    only: list[str] | None = None,
    dry_run: bool = False,
    nodes_dir: Path | None = None,
) -> int:
    """Install per-node requirements. Returns the number of nodes that failed."""
    requirements = find_node_requirements(nodes_dir)
    if only:
        wanted = {name.lower() for name in only}
        requirements = [item for item in requirements if item[0].lower() in wanted]
        missing = wanted - {name.lower() for name, _ in requirements}
        for name in sorted(missing):
            logger.warning("No node named %r with a requirements.txt was found", name)

    if not requirements:
        logger.info("No node dependencies to install.")
        return 0

    failures = 0
    for node_name, requirements_file in requirements:
        logger.info("Installing requirements for %s...", node_name)
        cmd = [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)]
        if dry_run:
            logger.info("  [dry-run] %s", " ".join(cmd))
            continue
        result = subprocess.run(cmd, check=False)
        if result.returncode == 0:
            logger.info("  ✓ %s dependencies installed", node_name)
        else:
            failures += 1
            logger.error("  ✗ Failed to install dependencies for %s", node_name)

    installed = len(requirements) - failures
    logger.info(
        "Done. Processed %d node(s); %d succeeded, %d failed.",
        len(requirements),
        installed if not dry_run else 0,
        failures,
    )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pynode-install-nodes",
        description="Install the per-node Python dependencies bundled with PyNode.",
    )
    parser.add_argument(
        "--node",
        action="append",
        dest="nodes",
        metavar="NodeName",
        help="Only install this node's requirements (repeatable).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List nodes that ship a requirements.txt and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be installed without running pip.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.list:
        for node_name, requirements_file in find_node_requirements():
            print(f"{node_name}: {requirements_file}")
        return 0

    failures = install_node_requirements(only=args.nodes, dry_run=args.dry_run)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
