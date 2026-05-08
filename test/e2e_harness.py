#!/usr/bin/env python3
"""End-to-end test harness for the Gemini Chrome Agent native messaging host.

Launches host.py as a subprocess, sends payloads via the Native Messaging
protocol, and asserts responses. Exercises all actions, error paths, and
protocol properties without requiring a browser.
"""

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

# Path to host.py relative to this file
HOST_PY = os.path.join(os.path.dirname(os.path.dirname(__file__)), "host.py")
MAX_OUTPUT_SIZE = 1024 * 1024  # 1MB — must match host.py


class NativeMessagingTransport:
    """Wraps a subprocess to send/receive length-prefixed JSON messages."""

    def __init__(self, process: subprocess.Popen):
        self.proc = process

    def send(self, message_dict: dict) -> None:
        encoded = json.dumps(message_dict).encode("utf-8")
        self.proc.stdin.write(struct.pack("@I", len(encoded)))
        self.proc.stdin.write(encoded)
        self.proc.stdin.flush()

    def recv(self, timeout: float = 10.0) -> dict:
        # Use select/poll when available to respect timeout on stdout
        if hasattr(self.proc.stdout, "fileno"):
            import select
            ready, _, _ = select.select([self.proc.stdout], [], [], timeout)
            if not ready:
                raise TimeoutError("No response from host within timeout")

        raw_length = self.proc.stdout.read(4)
        if len(raw_length) == 0:
            raise EOFError("Host closed stdout before sending length header")
        if len(raw_length) != 4:
            raise ValueError(f"Incomplete length header: got {len(raw_length)} bytes")

        message_length = struct.unpack("@I", raw_length)[0]
        message_bytes = self.proc.stdout.read(message_length)
        if len(message_bytes) != message_length:
            raise ValueError(
                f"Truncated body: expected {message_length} bytes, got {len(message_bytes)}"
            )
        return json.loads(message_bytes.decode("utf-8"))

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()


def make_request(action: str, **kwargs) -> tuple[str, dict]:
    """Build a request dict with a unique id."""
    req_id = kwargs.pop("id", f"test-{uuid.uuid4().hex[:8]}")
    payload = {"action": action, "id": req_id, **kwargs}
    return req_id, payload


class HostTestBase(unittest.TestCase):
    """Base class that manages a host.py subprocess, transport, and temp dir."""

    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen(
            [sys.executable, HOST_PY],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        cls.transport = NativeMessagingTransport(cls.proc)
        cls.temp_dir = tempfile.mkdtemp(prefix="e2e_harness_")

    @classmethod
    def tearDownClass(cls):
        # Guard against AttributeError if setUpClass raised before defining attrs.
        if hasattr(cls, "transport"):
            cls.transport.close()
        if hasattr(cls, "proc"):
            try:
                cls.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                cls.proc.terminate()
                cls.proc.wait(timeout=2)
        if hasattr(cls, "temp_dir"):
            shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _send_and_assert_success(self, action: str, **kwargs) -> dict:
        req_id, payload = make_request(action, **kwargs)
        self.transport.send(payload)
        response = self.transport.recv()

        self.assertEqual(response["id"], req_id, "Request/response id mismatch")
        self.assertEqual(response["status"], "success", f"Expected success, got: {response.get('error')}")
        self.assertIn("meta", response)
        self.assertIn("duration_ms", response["meta"])
        duration = response["meta"]["duration_ms"]
        self.assertIsInstance(duration, int)
        self.assertGreaterEqual(duration, 0)
        return response

    def _send_and_assert_error(self, action: str, **kwargs) -> dict:
        req_id, payload = make_request(action, **kwargs)
        self.transport.send(payload)
        response = self.transport.recv()

        self.assertEqual(response["id"], req_id, "Request/response id mismatch")
        self.assertEqual(response["status"], "error", f"Expected error, got: {response}")
        self.assertIn("meta", response)
        self.assertIn("duration_ms", response["meta"])
        duration = response["meta"]["duration_ms"]
        self.assertIsInstance(duration, int)
        self.assertGreaterEqual(duration, 0)
        self.assertIn("error", response)
        return response


class TestHostLifecycle(unittest.TestCase):
    """Verify host.py starts and stops cleanly."""

    def test_starts_cleanly(self):
        proc = subprocess.Popen(
            [sys.executable, HOST_PY],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.2)
        self.assertIsNone(proc.poll())
        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=2)
        self.assertEqual(proc.returncode, 0, "host.py should exit cleanly with code 0")


class TestAllActions(HostTestBase):
    """Happy-path tests for every supported action."""

    def test_run_shell(self):
        response = self._send_and_assert_success(
            "run_shell", command="echo 'hello world'"
        )
        self.assertIn("output", response)
        self.assertIn("hello world", response["output"])
        self.assertIn("code", response)
        self.assertEqual(response["code"], 0)

    def test_write_file(self):
        path = os.path.join(self.temp_dir, "write_test.txt")
        response = self._send_and_assert_success(
            "write_file", filepath=path, content="hello file"
        )
        self.assertIn("message", response)
        self.assertIn("written successfully", response["message"])
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "hello file")

    def test_read_file(self):
        path = os.path.join(self.temp_dir, "read_test.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("read me")
        response = self._send_and_assert_success("read_file", filepath=path)
        self.assertIn("output", response)
        self.assertEqual(response["output"], "read me")

    def test_list_files_directory(self):
        subdir = os.path.join(self.temp_dir, "list_dir")
        os.makedirs(subdir)
        for name in ("a.txt", "b.txt"):
            open(os.path.join(subdir, name), "w").close()
        response = self._send_and_assert_success("list_files", filepath=subdir)
        self.assertIn("output", response)
        self.assertIn("a.txt", response["output"])
        self.assertIn("b.txt", response["output"])

    def test_list_files_single_file(self):
        path = os.path.join(self.temp_dir, "single_file.txt")
        open(path, "w").close()
        response = self._send_and_assert_success("list_files", filepath=path)
        self.assertIn("output", response)
        self.assertIn("is a file, not a directory", response["output"])

    def test_git_status(self):
        git_dir = os.path.join(self.temp_dir, "git_repo")
        os.makedirs(git_dir)
        subprocess.run(["git", "init"], cwd=git_dir, check=True, capture_output=True)
        with open(os.path.join(git_dir, "foo.txt"), "w") as f:
            f.write("bar")
        subprocess.run(["git", "add", "."], cwd=git_dir, check=True, capture_output=True)
        response = self._send_and_assert_success("git_status", filepath=git_dir)
        self.assertIn("output", response)
        # Git status in a newly-created repo with staged files should contain a known string
        self.assertTrue(
            "On branch" in response["output"] or "nothing to commit" in response["output"] or "Changes to be committed" in response["output"],
            f"git_status output missing expected keywords: {response['output']!r}"
        )

    def test_git_diff(self):
        git_dir = os.path.join(self.temp_dir, "git_repo_diff")
        os.makedirs(git_dir)
        subprocess.run(["git", "init"], cwd=git_dir, check=True, capture_output=True)
        with open(os.path.join(git_dir, "foo.txt"), "w") as f:
            f.write("bar")
        subprocess.run(["git", "add", "."], cwd=git_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=git_dir, check=True, capture_output=True
        )
        with open(os.path.join(git_dir, "foo.txt"), "w") as f:
            f.write("baz")
        response = self._send_and_assert_success("git_diff", filepath=git_dir)
        self.assertIn("output", response)
        self.assertIn("baz", response["output"])

    def test_run_python_with_content(self):
        response = self._send_and_assert_success(
            "run_python", content="print('hello from python')"
        )
        self.assertIn("output", response)
        self.assertIn("hello from python", response["output"])
        self.assertIn("code", response)
        self.assertEqual(response["code"], 0)

    def test_run_python_with_filepath(self):
        path = os.path.join(self.temp_dir, "script.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write("print(2 + 2)")
        response = self._send_and_assert_success("run_python", filepath=path)
        self.assertIn("output", response)
        self.assertIn("4", response["output"])


class TestErrorCases(HostTestBase):
    """Tests for expected error responses."""

    def test_unknown_action(self):
        response = self._send_and_assert_error("fly_to_the_moon")
        self.assertIn("Unknown action", response["error"])

    def test_run_shell_missing_command(self):
        response = self._send_and_assert_error("run_shell")
        # host.py does .get('command') → None → subprocess.run(None, ...) raises TypeError
        self.assertIn("error", response)
        self.assertTrue(
            "command" in response["error"] or "NoneType" in response["error"],
            f"Error message should mention missing command or NoneType, got: {response['error']!r}"
        )

    def test_run_python_nonexistent_filepath(self):
        response = self._send_and_assert_error(
            "run_python", filepath="/does/not/exist/script.py"
        )
        self.assertIn("File not found", response["error"])

    def test_read_file_nonexistent(self):
        response = self._send_and_assert_error(
            "read_file", filepath="/does/not/exist/file.txt"
        )
        self.assertIn("File not found", response["error"])


class TestProtocolProperties(HostTestBase):
    """Tests for protocol-level behaviour: truncation, sequential ordering."""

    def test_large_output_truncation(self):
        """Generate >1MB of stdout and verify truncation notice is present."""
        # yes produces 2 bytes per line ("y\n"). 600_000 lines ≈ 1.2 MB.
        req_id, payload = make_request("run_shell", command="yes | head -n 600000")
        self.transport.send(payload)
        response = self.transport.recv(timeout=30.0)

        self.assertEqual(response["id"], req_id)
        self.assertEqual(response["status"], "success")
        self.assertIn("output", response)
        self.assertIn("[Output truncated", response["output"])
        output_bytes = response["output"].encode("utf-8")
        self.assertLessEqual(
            len(output_bytes),
            MAX_OUTPUT_SIZE + 200,
            "Truncated output should not greatly exceed MAX_OUTPUT_SIZE"
        )

    def test_sequential_requests_preserve_order(self):
        """Send multiple payloads back-to-back and verify responses correlate."""
        requests = [
            make_request("run_shell", command=f"echo '{i}'") for i in range(5)
        ]
        for req_id, payload in requests:
            self.transport.send(payload)

        for expected_id, _ in requests:
            response = self.transport.recv()
            self.assertEqual(response["id"], expected_id)
            self.assertEqual(response["status"], "success")
            self.assertIn("output", response)


if __name__ == "__main__":
    unittest.main(verbosity=2)
