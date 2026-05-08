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
    python3 main.py list_files /tmp
    python3 main.py git_status .
    python3 main.py git_diff .
    python3 main.py run_python --content "print('hello')"
    python3 main.py run_python --filepath /tmp/script.py
    python3 main.py interactive
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time


def _make_response(status: str, req_id: str = "cli", output=None, message=None, code=None, error=None):
    """Build a Protocol v2 shaped response dictionary."""
    resp = {
        "id": req_id,
        "status": status,
        "meta": {},
    }
    if output is not None:
        resp["output"] = output
    if message is not None:
        resp["message"] = message
    if code is not None:
        resp["code"] = code
    if error is not None:
        resp["error"] = error
    return resp


def run_shell(command: str, req_id: str = "cli") -> dict:
    """Execute a shell command and return the result as a dictionary."""
    start = time.perf_counter()
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

        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "success",
            req_id,
            output=combined_output,
            code=result.returncode,
        ) | {"meta": {"duration_ms": duration_ms}}
    except subprocess.TimeoutExpired:
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "error",
            req_id,
            error="Command timed out after 30 seconds.",
        ) | {"meta": {"duration_ms": duration_ms}}
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "error",
            req_id,
            error=f"Subprocess Exception: {str(e)}",
        ) | {"meta": {"duration_ms": duration_ms}}


def write_file(filepath: str, content: str, req_id: str = "cli") -> dict:
    """Write content to a file."""
    start = time.perf_counter()
    try:
        filepath = os.path.expanduser(filepath)
        directory = os.path.dirname(filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "success",
            req_id,
            message=f"File {filepath} written successfully.",
        ) | {"meta": {"duration_ms": duration_ms}}
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "error",
            req_id,
            error=f"File write error: {str(e)}",
        ) | {"meta": {"duration_ms": duration_ms}}


def read_file(filepath: str, req_id: str = "cli") -> dict:
    """Read content from a file."""
    start = time.perf_counter()
    try:
        filepath = os.path.expanduser(filepath)
        if not os.path.exists(filepath):
            duration_ms = round((time.perf_counter() - start) * 1000)
            return _make_response(
                "error",
                req_id,
                error=f"File not found: {filepath}",
            ) | {"meta": {"duration_ms": duration_ms}}
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "success",
            req_id,
            output=content,
        ) | {"meta": {"duration_ms": duration_ms}}
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "error",
            req_id,
            error=f"File read error: {str(e)}",
        ) | {"meta": {"duration_ms": duration_ms}}


def list_files(filepath: str, req_id: str = "cli") -> dict:
    """List files in a directory."""
    start = time.perf_counter()
    try:
        filepath = os.path.expanduser(filepath)
        if os.path.isdir(filepath):
            entries = os.listdir(filepath)
            output = "\n".join(entries)
        elif os.path.exists(filepath):
            output = f"{filepath} is a file, not a directory."
        else:
            output = f"Path not found: {filepath}"
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "success",
            req_id,
            output=output,
        ) | {"meta": {"duration_ms": duration_ms}}
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "error",
            req_id,
            error=f"List error: {str(e)}",
        ) | {"meta": {"duration_ms": duration_ms}}


def git_status(filepath: str, req_id: str = "cli") -> dict:
    """Run git status in a directory."""
    start = time.perf_counter()
    try:
        directory = os.path.expanduser(filepath)
        result = subprocess.run(
            ["git", "status"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout or ""
        if not output.strip():
            output = f"[Command completed with exit code {result.returncode} and no output]"
        duration_ms = round((time.perf_counter() - start) * 1000)
        meta = {"duration_ms": duration_ms}
        if result.returncode != 0:
            return _make_response("error", req_id, error=output) | {"meta": meta}
        return _make_response("success", req_id, output=output) | {"meta": meta}
    except subprocess.TimeoutExpired:
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "error",
            req_id,
            error="Git status timed out after 30 seconds.",
        ) | {"meta": {"duration_ms": duration_ms}}
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "error",
            req_id,
            error=f"Git status error: {str(e)}",
        ) | {"meta": {"duration_ms": duration_ms}}


def git_diff(filepath: str, req_id: str = "cli") -> dict:
    """Run git diff in a directory."""
    start = time.perf_counter()
    try:
        directory = os.path.expanduser(filepath)
        result = subprocess.run(
            ["git", "diff"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout or ""
        if not output.strip():
            output = f"[Command completed with exit code {result.returncode} and no output]"
        duration_ms = round((time.perf_counter() - start) * 1000)
        meta = {"duration_ms": duration_ms}
        if result.returncode != 0:
            return _make_response("error", req_id, error=output) | {"meta": meta}
        return _make_response("success", req_id, output=output) | {"meta": meta}
    except subprocess.TimeoutExpired:
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "error",
            req_id,
            error="Git diff timed out after 30 seconds.",
        ) | {"meta": {"duration_ms": duration_ms}}
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "error",
            req_id,
            error=f"Git diff error: {str(e)}",
        ) | {"meta": {"duration_ms": duration_ms}}


def run_python(filepath=None, content=None, req_id: str = "cli") -> dict:
    """Run a Python script from file or inline content."""
    start = time.perf_counter()
    script_path = None
    temp_file = None
    try:
        if content is not None:
            temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
            temp_file.write(content)
            temp_file.close()
            script_path = temp_file.name
        elif filepath is not None:
            script_path = os.path.expanduser(filepath)
            if not os.path.exists(script_path):
                duration_ms = round((time.perf_counter() - start) * 1000)
                return _make_response(
                    "error",
                    req_id,
                    error=f"File not found: {script_path}",
                ) | {"meta": {"duration_ms": duration_ms}}
        else:
            duration_ms = round((time.perf_counter() - start) * 1000)
            return _make_response(
                "error",
                req_id,
                error="Either filepath or content must be provided for run_python.",
            ) | {"meta": {"duration_ms": duration_ms}}

        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout or ""
        if result.stderr:
            output += f"\n--- Standard Error ---\n{result.stderr}"
        if not output.strip():
            output = f"[Command completed with exit code {result.returncode} and no output]"
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "success",
            req_id,
            output=output,
            code=result.returncode,
        ) | {"meta": {"duration_ms": duration_ms}}
    except subprocess.TimeoutExpired:
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "error",
            req_id,
            error="Python execution timed out after 30 seconds.",
        ) | {"meta": {"duration_ms": duration_ms}}
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        return _make_response(
            "error",
            req_id,
            error=f"Python execution error: {str(e)}",
        ) | {"meta": {"duration_ms": duration_ms}}
    finally:
        if temp_file is not None:
            try:
                os.unlink(temp_file.name)
            except Exception:
                pass


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
            req_id = msg.get("id", "interactive")

            if action == "run_shell":
                result = run_shell(msg.get("command", ""), req_id)
            elif action == "write_file":
                result = write_file(msg.get("filepath", ""), msg.get("content", ""), req_id)
            elif action == "read_file":
                result = read_file(msg.get("filepath", ""), req_id)
            elif action == "list_files":
                result = list_files(msg.get("filepath", ""), req_id)
            elif action == "git_status":
                result = git_status(msg.get("filepath", "."), req_id)
            elif action == "git_diff":
                result = git_diff(msg.get("filepath", "."), req_id)
            elif action == "run_python":
                result = run_python(
                    filepath=msg.get("filepath"),
                    content=msg.get("content"),
                    req_id=req_id,
                )
            else:
                result = _make_response("error", req_id, error=f"Unknown action: {action}")

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
  %(prog)s list_files /tmp
  %(prog)s git_status .
  %(prog)s git_diff .
  %(prog)s run_python --content "print('hello')"
  %(prog)s run_python --filepath /tmp/script.py
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

    # list_files
    list_parser = subparsers.add_parser("list_files", help="List files in a directory")
    list_parser.add_argument("filepath", help="Directory path")

    # git_status
    git_status_parser = subparsers.add_parser("git_status", help="Run git status in a directory")
    git_status_parser.add_argument("filepath", nargs="?", default=".", help="Directory path (default: .)")

    # git_diff
    git_diff_parser = subparsers.add_parser("git_diff", help="Run git diff in a directory")
    git_diff_parser.add_argument("filepath", nargs="?", default=".", help="Directory path (default: .)")

    # run_python
    python_parser = subparsers.add_parser("run_python", help="Run a Python script")
    python_parser.add_argument("--filepath", help="Path to Python script")
    python_parser.add_argument("--content", help="Python code to execute inline")

    # interactive
    subparsers.add_parser("interactive", help="Start interactive JSON command mode")

    args = parser.parse_args()

    if args.action == "run_shell":
        result = run_shell(args.command)
    elif args.action == "write_file":
        result = write_file(args.filepath, args.content)
    elif args.action == "read_file":
        result = read_file(args.filepath)
    elif args.action == "list_files":
        result = list_files(args.filepath)
    elif args.action == "git_status":
        result = git_status(args.filepath)
    elif args.action == "git_diff":
        result = git_diff(args.filepath)
    elif args.action == "run_python":
        result = run_python(filepath=args.filepath, content=args.content)
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
