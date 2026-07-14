"""Derive a pinned pip requirements file from uv.lock, without needing uv installed.

`uv sync` resolves the workspace (ltx-core, ltx-pipelines, ltx-trainer) against
platform/Python-version markers and writes the result to uv.lock. This script
replays that resolution for one fixed environment (a specific Python version +
platform) and prints the flat, pinned dependency set as `name==version` lines
suitable for `pip install -r`.

Usage:
    python generate_from_uv_lock.py --python 3.12.4 [--platform linux] \
        [--machine x86_64] > requirements-linux-py312.txt

Run from anywhere; it looks for uv.lock at the repository root (two levels up).
"""

import argparse
import sys
import tomllib
from pathlib import Path

from packaging.markers import Marker

WORKSPACE_NAMES = {"ltx-core", "ltx-pipelines", "ltx-trainer", "ltx-kernels"}
ROOTS = ("ltx-core", "ltx-pipelines", "ltx-trainer")


def make_env(python_full_version: str, sys_platform: str, platform_machine: str) -> dict:
    python_version = ".".join(python_full_version.split(".")[:2])
    return {
        "python_full_version": python_full_version,
        "python_version": python_version,
        "sys_platform": sys_platform,
        "platform_machine": platform_machine,
        "platform_system": "Linux" if sys_platform == "linux" else sys_platform,
        "platform_release": "",
        "platform_version": "",
        "implementation_name": "cpython",
        "implementation_version": python_full_version,
        "os_name": "posix" if sys_platform != "win32" else "nt",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="3.11.4", help="Target python_full_version")
    parser.add_argument("--platform", default="linux", help="Target sys_platform")
    parser.add_argument("--machine", default="x86_64", help="Target platform_machine")
    parser.add_argument(
        "--lock",
        default=Path(__file__).resolve().parents[1] / "uv.lock",
        type=Path,
        help="Path to uv.lock",
    )
    args = parser.parse_args()

    env = make_env(args.python, args.platform, args.machine)

    with args.lock.open("rb") as f:
        data = tomllib.load(f)

    by_name: dict[str, list[dict]] = {}
    for p in data["package"]:
        by_name.setdefault(p["name"], []).append(p)

    def marker_ok(marker_str: str | None) -> bool:
        return True if not marker_str else Marker(marker_str).evaluate(env)

    def entry_applies(p: dict) -> bool:
        markers = p.get("resolution-markers")
        return True if not markers else any(Marker(m).evaluate(env) for m in markers)

    def applicable_entry(name: str) -> dict | None:
        candidates = [p for p in by_name.get(name, []) if entry_applies(p)]
        return candidates[0] if len(candidates) == 1 else None

    visited: dict[str, str] = {}
    order: list[str] = []
    ok = True

    def visit(name: str) -> None:
        nonlocal ok
        p = applicable_entry(name)
        if p is None:
            print(f"WARNING: could not uniquely resolve {name!r} for target env", file=sys.stderr)
            ok = False
            return
        for dep in p.get("dependencies", []):
            if not marker_ok(dep.get("marker")):
                continue
            dep_name = dep["name"]
            if dep_name in WORKSPACE_NAMES:
                continue
            dep_p = applicable_entry(dep_name)
            if dep_p is None:
                print(f"WARNING: could not uniquely resolve {dep_name!r} for target env", file=sys.stderr)
                ok = False
                continue
            ver = dep_p["version"]
            if dep_name not in visited:
                visited[dep_name] = ver
                order.append(dep_name)
                visit(dep_name)
            elif visited[dep_name] != ver:
                print(
                    f"WARNING: version conflict for {dep_name!r}: {visited[dep_name]} vs {ver}",
                    file=sys.stderr,
                )
                ok = False

    for root in ROOTS:
        visit(root)

    for name in sorted(order):
        print(f"{name}=={visited[name]}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
