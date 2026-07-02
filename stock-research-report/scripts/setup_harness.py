#!/usr/bin/env python3
"""One-command Ark harness setup for the stock-research-report skill."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


SUPPORTED_TARGETS = ("codex", "openclaw")


def run_command(command: list[str], *, dry_run: bool) -> int:
    print("$ " + " ".join(command))
    if dry_run:
        return 0
    completed = subprocess.run(command)
    return completed.returncode


def build_command(args: argparse.Namespace) -> list[str]:
    command = ["arkcli", "helper"]
    if args.mode == "mcp-only":
        command.extend(["mcp", args.target])
    else:
        command.extend(["configure", args.target, "--with-mcp"])

    if args.target == "codex":
        if args.codex_config_scope:
            command.extend(["--codex-config-scope", args.codex_config_scope])
        if args.codex_profile:
            command.extend(["--codex-profile", args.codex_profile])

    if args.ov_resource:
        command.extend(["--ov-resource", args.ov_resource])

    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure Ark Agent Plan harness tools for stock-research-report."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="openclaw",
        choices=SUPPORTED_TARGETS,
        help="Agent to configure. Defaults to openclaw.",
    )
    parser.add_argument(
        "--mode",
        choices=("configure", "mcp-only"),
        default="configure",
        help="Use configure to set model/provider plus MCP, or mcp-only to inject tools only.",
    )
    parser.add_argument(
        "--codex-config-scope",
        choices=("profile", "global"),
        help="Codex-only config scope passed through to arkcli helper.",
    )
    parser.add_argument(
        "--codex-profile",
        help="Codex-only profile name passed through to arkcli helper.",
    )
    parser.add_argument(
        "--ov-resource",
        help="Optional OpenViking resource name when arkcli asks for an explicit resource.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the arkcli command without running it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.target != "codex" and (args.codex_config_scope or args.codex_profile):
        print("ERROR: --codex-config-scope and --codex-profile only apply to target=codex.", file=sys.stderr)
        return 2

    if shutil.which("arkcli") is None:
        print("ERROR: arkcli is not installed or not on PATH.", file=sys.stderr)
        print("Install or log in to arkcli first, then rerun this script.", file=sys.stderr)
        return 127

    command = build_command(args)
    code = run_command(command, dry_run=args.dry_run)
    if code == 0 and not args.dry_run:
        print("\nSetup command completed. Restart the target agent before using $stock-research-report.")
        if args.target == "codex" and args.codex_config_scope != "global":
            print("For Codex profile-mode setup, launch Codex with the configured profile if needed.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
