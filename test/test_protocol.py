"""Unit tests for the length-prefixed JSON Native Messaging protocol.

These tests mirror the encode/decode logic in host.py but operate against
in-memory streams so they can be exercised without a live browser host pipe.

What is tested:
- Frame encoding: JSON dict → 4-byte little-endian length prefix + JSON bytes
- Frame decoding: reading length header and body from a byte stream
- Error handling: EOF, truncated headers, truncated bodies, malformed JSON
- Large payload handling: the standalone truncate_output helper (mirrors host.py)

What is NOT tested:
- Timeout handling: host.py performs blocking reads on stdin with no timeout
  mechanism. Timeout safety is out of scope for the current protocol layer.
"""

import io
import json
import struct
import unittest
from unittest.mock import patch

import host

MAX_OUTPUT_SIZE = 1024 * 1024  # 1MB — must match host.py


def truncate_output(text, max_bytes=MAX_OUTPUT_SIZE):
    """Mirrors host.py truncate_output for standalone testing."""
    if text is None:
        text = ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated + f"\n\n[Output truncated: exceeded {max_bytes} bytes]"


def encode_frame(message_dict: dict) -> bytes:
    """Encode a message dict into the Native Messaging frame format."""
    encoded = json.dumps(message_dict).encode("utf-8")
    return struct.pack("@I", len(encoded)) + encoded


def decode_frame(stream: io.BytesIO) -> dict:
    """Decode a single Native Messaging frame from a byte stream."""
    raw_length = stream.read(4)
    if len(raw_length) == 0:
        raise EOFError("Stream closed — no data to read")
    if len(raw_length) != 4:
        raise ValueError(f"Incomplete length header: expected 4 bytes, got {len(raw_length)}")

    message_length = struct.unpack("@I", raw_length)[0]
    message_bytes = stream.read(message_length)
    if len(message_bytes) != message_length:
        raise ValueError(
            f"Truncated body: expected {message_length} bytes, got {len(message_bytes)}"
        )
    return json.loads(message_bytes.decode("utf-8"))


class TestFrameEncoding(unittest.TestCase):
    """Tests for encode_frame."""

    def test_simple_dict(self):
        payload = {"action": "run_shell", "command": "echo hello"}
        frame = encode_frame(payload)

        # First 4 bytes = little-endian length of the JSON blob
        expected_json = json.dumps(payload).encode("utf-8")
        expected_length = struct.pack("@I", len(expected_json))
        self.assertEqual(frame[:4], expected_length)
        self.assertEqual(frame[4:], expected_json)

    def test_empty_dict(self):
        payload = {}
        frame = encode_frame(payload)
        expected_json = b"{}"
        self.assertEqual(frame[:4], struct.pack("@I", 2))
        self.assertEqual(frame[4:], expected_json)

    def test_unicode_payload(self):
        payload = {"action": "write_file", "content": "日本語テキスト"}
        frame = encode_frame(payload)
        expected_json = json.dumps(payload).encode("utf-8")
        self.assertEqual(frame[:4], struct.pack("@I", len(expected_json)))
        self.assertEqual(frame[4:], expected_json)


class TestFrameDecoding(unittest.TestCase):
    """Tests for decode_frame."""

    def test_roundtrip(self):
        original = {"action": "read_file", "filepath": "/tmp/test.txt", "id": "abc-123"}
        frame = encode_frame(original)
        stream = io.BytesIO(frame)
        decoded = decode_frame(stream)
        self.assertEqual(decoded, original)

    def test_multiple_frames_sequential(self):
        messages = [
            {"action": "run_shell", "command": "uname -a", "id": "1"},
            {"action": "write_file", "filepath": "/tmp/a", "content": "b", "id": "2"},
            {"action": "read_file", "filepath": "/tmp/a", "id": "3"},
        ]
        stream = io.BytesIO(b"".join(encode_frame(m) for m in messages))
        for expected in messages:
            self.assertEqual(decode_frame(stream), expected)
        # Stream should now be exhausted
        with self.assertRaises(EOFError):
            decode_frame(stream)

    def test_empty_stream_raises_eof(self):
        stream = io.BytesIO(b"")
        with self.assertRaises(EOFError):
            decode_frame(stream)

    def test_truncated_length_header(self):
        stream = io.BytesIO(b"\x02\x00")  # only 2 bytes, need 4
        with self.assertRaises(ValueError) as ctx:
            decode_frame(stream)
        self.assertIn("Incomplete length header", str(ctx.exception))

    def test_truncated_body(self):
        # Length header says 100 bytes but body is only 5
        stream = io.BytesIO(struct.pack("@I", 100) + b'{"a"')
        with self.assertRaises(ValueError) as ctx:
            decode_frame(stream)
        self.assertIn("Truncated body", str(ctx.exception))

    def test_invalid_length_header(self):
        # Length = 0xFFFFFFFF (way larger than any reasonable message)
        stream = io.BytesIO(struct.pack("@I", 0xFFFFFFFF))
        with self.assertRaises(ValueError) as ctx:
            decode_frame(stream)
        self.assertIn("Truncated body", str(ctx.exception))

    def test_malformed_json(self):
        raw = b"not json"
        stream = io.BytesIO(struct.pack("@I", len(raw)) + raw)
        with self.assertRaises(json.JSONDecodeError):
            decode_frame(stream)


class TestLargePayloadHandling(unittest.TestCase):
    """Tests for >1MB truncation behavior."""

    def test_truncate_output_exactly_at_limit(self):
        text = "x" * MAX_OUTPUT_SIZE
        result = truncate_output(text)
        self.assertEqual(result, text)

    def test_truncate_output_exceeds_limit(self):
        text = "x" * (MAX_OUTPUT_SIZE + 1000)
        result = truncate_output(text)
        self.assertIn("[Output truncated", result)
        # UTF-8 encoded length should not exceed limit by much
        self.assertLessEqual(len(result.encode("utf-8")), MAX_OUTPUT_SIZE + 200)

    def test_truncate_output_with_multibyte_characters(self):
        # Each emoji is 4 bytes in UTF-8
        emoji = "🎉"
        count = (MAX_OUTPUT_SIZE // 4) + 100
        text = emoji * count
        result = truncate_output(text)
        self.assertIn("[Output truncated", result)
        self.assertLessEqual(len(result.encode("utf-8")), MAX_OUTPUT_SIZE + 200)

    def test_truncate_output_none(self):
        self.assertEqual(truncate_output(None), "")

    def test_frame_encoding_does_not_truncate(self):
        # The protocol layer should NOT truncate — it just encodes
        # truncation is a host.py concern
        big_text = "y" * (MAX_OUTPUT_SIZE + 5000)
        payload = {"output": big_text}
        frame = encode_frame(payload)
        stream = io.BytesIO(frame)
        decoded = decode_frame(stream)
        self.assertEqual(decoded["output"], big_text)


class TestActionResponseShapes(unittest.TestCase):
    """Tests for action-specific response shapes from host.py handlers."""

    @patch('host.send_message')
    def test_run_shell_response_includes_code(self, mock_send):
        host.handle_run_shell({'id': 'test-1', 'command': 'echo hello'})
        mock_send.assert_called_once()
        response = mock_send.call_args[0][0]
        self.assertEqual(response['status'], 'success')
        self.assertIn('code', response)
        self.assertIn('meta', response)
        self.assertIn('duration_ms', response['meta'])

    @patch('host.send_message')
    def test_run_shell_error_response_includes_code(self, mock_send):
        host.handle_run_shell({'id': 'test-1', 'command': 'exit 42'})
        mock_send.assert_called_once()
        response = mock_send.call_args[0][0]
        self.assertEqual(response['status'], 'success')
        self.assertIn('code', response)
        self.assertEqual(response['code'], 42)
        self.assertIn('meta', response)
        self.assertIn('duration_ms', response['meta'])

    @patch('host.send_message')
    def test_git_status_response_excludes_code(self, mock_send):
        host.handle_git_status({'id': 'test-1', 'filepath': '/tmp'})
        mock_send.assert_called_once()
        response = mock_send.call_args[0][0]
        self.assertNotIn('code', response)
        self.assertIn('meta', response)
        self.assertIn('duration_ms', response['meta'])

    @patch('host.send_message')
    def test_git_diff_response_excludes_code(self, mock_send):
        host.handle_git_diff({'id': 'test-1', 'filepath': '/tmp'})
        mock_send.assert_called_once()
        response = mock_send.call_args[0][0]
        self.assertNotIn('code', response)
        self.assertIn('meta', response)
        self.assertIn('duration_ms', response['meta'])

    @patch('host.send_message')
    def test_run_python_with_content_includes_code(self, mock_send):
        host.handle_run_python({'id': 'test-1', 'content': 'print("hello")'})
        mock_send.assert_called_once()
        response = mock_send.call_args[0][0]
        self.assertEqual(response['status'], 'success')
        self.assertIn('code', response)
        self.assertIn('meta', response)
        self.assertIn('duration_ms', response['meta'])


if __name__ == "__main__":
    unittest.main(verbosity=2)
