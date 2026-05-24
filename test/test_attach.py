import os
import base64
import tempfile
import unittest

from host import read_file_b64, chunk_b64


class TestReadFileB64(unittest.TestCase):
    def test_reads_and_base64_encodes(self):
        with tempfile.NamedTemporaryFile('wb', suffix='.txt', delete=False) as f:
            f.write(b'hello')
            path = f.name
        try:
            mime, b64 = read_file_b64(path, max_bytes=1024)
            self.assertEqual(base64.b64decode(b64), b'hello')
            self.assertTrue(mime)  # some mime guessed or octet-stream
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_file_b64('/no/such/file.xyz', max_bytes=1024)

    def test_too_large_raises_valueerror(self):
        with tempfile.NamedTemporaryFile('wb', suffix='.bin', delete=False) as f:
            f.write(b'x' * 100)
            path = f.name
        try:
            with self.assertRaises(ValueError):
                read_file_b64(path, max_bytes=10)
        finally:
            os.unlink(path)


class TestChunkB64(unittest.TestCase):
    def test_splits_and_rejoins_exactly(self):
        b64 = 'A' * 1000
        chunks = chunk_b64(b64, 256)
        self.assertEqual(len(chunks), 4)  # 256,256,256,232
        self.assertEqual(''.join(chunks), b64)

    def test_single_chunk_when_small(self):
        self.assertEqual(chunk_b64('abc', 256), ['abc'])

    def test_empty_string(self):
        self.assertEqual(chunk_b64('', 256), [])


if __name__ == '__main__':
    unittest.main()
