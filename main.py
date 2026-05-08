#!/usr/bin/env python3
"""
Gemini Agent CLI - Standalone utility for testing agent actions locally.

This script provides a command-line interface to the same actions available
through the Chrome Extension Native Messaging host (host.py). Use it to test
file operations and shell commands without needing the browser extension.

Usage:
    python3 main.py run_shell "ls -la ~"
    python3 main.py write_file /tmp/test.txt "Hello World"
    python3 main.py read_file /tmp/test.txt
    python3 main.py interactive
"""

import argparse
import json
import os
import subprocess
import sys


def run_shell(command: str) -> dict:
    """Execute a shell command and return the result as a dictionary."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout or ""
        error = result.stderr or ""
        combined_output = output
        if error:
            combined_output += f"\n--- Standard Error ---\n{error}"

        if not combined_output.strip():
            combined_output = (
                f"[Command completed with exit code {result.returncode} and no output]"
            )

        return {
            "status": "success",
            "output": combined_output,
            "code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Command timed out after 30 seconds."}
    except Exception as e:
        return {"status": "error", "error": f"Subprocess Exception: {str(e)}"}


def write_file(filepath: str, content: str) -> dict:
    """Write content to a file."""
    try:
        filepath = os.path.expanduser(filepath)
        directory = os.path.dirname(filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return {
            "status": "success",
            "message": f"File {filepath} written successfully.",
        }
    except Exception as e:
        return {"status": "error", "error": f"File write error: {str(e)}"}


def read_file(filepath: str) -> dict:
    """Read content from a file."""
    try:
        filepath = os.path.expanduser(filepath)
        if not os.path.exists(filepath):
            return {"status": "error", "error": f"File not found: {filepath}"}
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "output": content}
    except Exception as e:
        return {"status": "error", "error": f"File read error: {str(e)}"}


def interactive_mode() -> None:
    """Run an interactive REPL for agent actions."""
    print("Gemini Agent CLI — Interactive Mode")
    print("Enter JSON commands (type 'quit', 'exit', or Ctrl+C to quit):\n")

    while True:
        try:
            user_input = input("> ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                break

            msg = json.loads(user_input)
            action = msg.get("action")

            if action == "run_shell":
                result = run_shell(msg.get("command", ""))
            elif action == "write_file":
                result = write_file(msg.get("filepath", ""), msg.get("content", ""))
            elif action == "read_file":
                result = read_file(msg.get("filepath", ""))
            else:
                result = {"status": "error", "error": f"Unknown action: {action}"}

            print(json.dumps(result, indent=2))

        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}")
        except KeyboardInterrupt:
            print("\nExiting...")
            break


def main() -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Gemini Agent CLI — Test agent actions locally without the browser extension.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s run_shell "git status"
  %(prog)s write_file ~/notes.txt "My notes"
  %(prog)s read_file ~/notes.txt
  %(prog)s interactive
        """,
    )

    subparsers = parser.add_subparsers(dest="action", help="Available actions")

    # run_shell
    shell_parser = subparsers.add_parser("run_shell", help="Execute a shell command")
    shell_parser.add_argument("command", help="The shell command to execute")

    # write_file
    write_parser = subparsers.add_parser("write_file", help="Write content to a file")
    write_parser.add_argument("filepath", help="Target file path")
    write_parser.add_argument("content", help="Content to write")

    # read_file
    read_parser = subparsers.add_parser("read_file", help="Read content from a file")
    read_parser.add_argument("filepath", help="Source file path")

    # interactive
    subparsers.add_parser("interactive", help="Start interactive JSON command mode")

    args = parser.parse_args()

    if args.action == "run_shell":
        result = run_shell(args.command)
    elif args.action == "write_file":
        result = write_file(args.filepath, args.content)
    elif args.action == "read_file":
        result = read_file(args.filepath)
    elif args.action == "interactive":
        interactive_mode()
        return 0
    else:
        parser.print_help()
        return 1

    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
