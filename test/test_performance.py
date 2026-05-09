#!/usr/bin/env python3
"""
Performance tests for the Gemini Local Agent native messaging host.

Measures:
  - Round-trip latency per action type
  - Message throughput (msgs/sec)
  - Large payload handling time
  - Shell execution overhead vs Python execution

Usage:
  python3 -m unittest test.test_performance -v
"""

import json
import struct
import subprocess
import time
import unittest


class HostPerfTestBase(unittest.TestCase):
    """Base class that spawns the host process for each test."""

    def setUp(self):
        self.proc = subprocess.Popen(
            ["python3", "host.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.stdout.close()
            if self.proc.stderr:
                self.proc.stderr.close()
            self.proc.wait(timeout=2)

    def send(self, msg: dict) -> dict:
        """Send a message and read the response."""
        raw = json.dumps(msg).encode("utf-8")
        length = struct.pack("@I", len(raw))
        self.proc.stdin.write(length + raw)
        self.proc.stdin.flush()

        header = self.proc.stdout.read(4)
        if len(header) < 4:
            raise EOFError("Host closed stream")
        msg_len = struct.unpack("@I", header)[0]
        response = self.proc.stdout.read(msg_len).decode("utf-8")
        return json.loads(response)


class TestRoundTripLatency(HostPerfTestBase):
    """Measure round-trip latency for each supported action."""

    def _measure_latency(self, payload: dict, iterations: int = 10) -> dict:
        """Run multiple iterations and return min/avg/max latency."""
        latencies = []
        for _ in range(iterations):
            start = time.perf_counter()
            resp = self.send(payload)
            elapsed = (time.perf_counter() - start) * 1000  # ms
            latencies.append(elapsed)
            self.assertEqual(resp["status"], "success", resp.get("error"))

        return {
            "min_ms": min(latencies),
            "avg_ms": sum(latencies) / len(latencies),
            "max_ms": max(latencies),
            "iterations": iterations,
        }

    def test_run_shell_latency(self):
        """run_shell should complete in under 50ms avg."""
        stats = self._measure_latency(
            {"action": "run_shell", "command": "echo hello", "id": "perf-shell"}
        )
        self.assertLess(stats["avg_ms"], 50, f"Average latency too high: {stats}")
        self.assertLess(stats["max_ms"], 100, f"Max latency too high: {stats}")
        print(f"\n  run_shell latency: {stats['avg_ms']:.2f}ms avg, {stats['min_ms']:.2f}ms min, {stats['max_ms']:.2f}ms max")

    def test_run_python_latency(self):
        """run_python should complete in under 50ms avg."""
        stats = self._measure_latency(
            {"action": "run_python", "content": "print('hello')", "id": "perf-py"}
        )
        self.assertLess(stats["avg_ms"], 50, f"Average latency too high: {stats}")
        print(f"\n  run_python latency: {stats['avg_ms']:.2f}ms avg")

    def test_git_status_latency(self):
        """git_status on this repo should complete in under 100ms avg."""
        stats = self._measure_latency(
            {"action": "git_status", "path": ".", "id": "perf-git"}
        )
        self.assertLess(stats["avg_ms"], 100, f"Average latency too high: {stats}")
        print(f"\n  git_status latency: {stats['avg_ms']:.2f}ms avg")

    def test_list_files_latency(self):
        """list_files should complete in under 50ms avg."""
        stats = self._measure_latency(
            {"action": "list_files", "filepath": ".", "id": "perf-ls"}
        )
        self.assertLess(stats["avg_ms"], 50, f"Average latency too high: {stats}")
        print(f"\n  list_files latency: {stats['avg_ms']:.2f}ms avg")


class TestThroughput(HostPerfTestBase):
    """Measure how many messages the host can process per second."""

    def test_small_payload_throughput(self):
        """Host should handle at least 20 messages/sec."""
        count = 50
        start = time.perf_counter()
        for i in range(count):
            resp = self.send(
                {"action": "run_shell", "command": f"echo {i}", "id": f"tput-{i}"}
            )
            self.assertEqual(resp["status"], "success")
        elapsed = time.perf_counter() - start
        msgs_per_sec = count / elapsed

        print(f"\n  Throughput: {msgs_per_sec:.1f} msgs/sec ({count} msgs in {elapsed*1000:.0f}ms)")
        self.assertGreater(msgs_per_sec, 20, f"Throughput too low: {msgs_per_sec:.1f} msgs/sec")


class TestLargePayloadPerf(HostPerfTestBase):
    """Measure performance with large payloads."""

    def test_10kb_write_file(self):
        """Writing a 10KB file should complete in under 100ms."""
        content = "x" * 10000
        start = time.perf_counter()
        resp = self.send(
            {
                "action": "write_file",
                "filepath": "/tmp/gla_perf_test_10k.txt",
                "content": content,
                "id": "perf-10k",
            }
        )
        elapsed = (time.perf_counter() - start) * 1000

        self.assertEqual(resp["status"], "success", resp.get("error"))
        self.assertLess(elapsed, 100, f"10KB write took {elapsed:.1f}ms")
        print(f"\n  10KB write_file: {elapsed:.1f}ms")

    def test_100kb_write_file(self):
        """Writing a 100KB file should complete in under 200ms."""
        content = "y" * 100000
        start = time.perf_counter()
        resp = self.send(
            {
                "action": "write_file",
                "filepath": "/tmp/gla_perf_test_100k.txt",
                "content": content,
                "id": "perf-100k",
            }
        )
        elapsed = (time.perf_counter() - start) * 1000

        self.assertEqual(resp["status"], "success", resp.get("error"))
        self.assertLess(elapsed, 200, f"100KB write took {elapsed:.1f}ms")
        print(f"\n  100KB write_file: {elapsed:.1f}ms")

    def test_1mb_output_truncation_perf(self):
        """Generating 1MB+ of stdout should be truncated quickly."""
        start = time.perf_counter()
        resp = self.send(
            {
                "action": "run_shell",
                "command": "yes | head -n 600000",
                "id": "perf-1mb",
            }
        )
        elapsed = (time.perf_counter() - start) * 1000

        self.assertEqual(resp["status"], "success")
        self.assertIn("truncated", resp.get("output", "").lower())
        self.assertLess(elapsed, 500, f"1MB truncation took {elapsed:.1f}ms")
        print(f"\n  1MB truncation: {elapsed:.1f}ms")


class TestShellVsPythonOverhead(HostPerfTestBase):
    """Compare execution overhead of shell vs Python."""

    def test_shell_overhead(self):
        """Empty shell command baseline."""
        start = time.perf_counter()
        resp = self.send({"action": "run_shell", "command": "true", "id": "perf-true"})
        elapsed = (time.perf_counter() - start) * 1000
        self.assertEqual(resp["status"], "success")
        print(f"\n  Shell 'true' overhead: {elapsed:.2f}ms")

    def test_python_overhead(self):
        """Empty Python command baseline."""
        start = time.perf_counter()
        resp = self.send({"action": "run_python", "content": "pass", "id": "perf-pass"})
        elapsed = (time.perf_counter() - start) * 1000
        self.assertEqual(resp["status"], "success")
        print(f"\n  Python 'pass' overhead: {elapsed:.2f}ms")


if __name__ == "__main__":
    unittest.main()
