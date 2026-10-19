"""Read byte-bounded streams without trusting headers or consuming later chunks."""
from types import SimpleNamespace
import unittest

from fastapi import HTTPException

from app.api.request_body import read_limited_body

DETAIL = {'code': 'body_too_large', 'message': 'fixture limit'}


class LimitedBodyTests(unittest.IsolatedAsyncioTestCase):
    def request(self, chunks):
        self.seen = []
        async def stream():
            for index, chunk in enumerate(chunks):
                self.seen.append(index)
                yield chunk
        return SimpleNamespace(stream=stream, headers={'content-length': '1'})

    async def test_exact_boundary_and_empty_chunks(self):
        body = await read_limited_body(self.request([b'ab', b'', b'cdefgh']), 8, detail=DETAIL)
        self.assertEqual(body, b'abcdefgh')
        self.assertEqual(self.seen, [0, 1, 2])

    async def test_overflow_stops_before_later_chunks_even_with_false_length(self):
        with self.assertRaises(HTTPException) as caught:
            await read_limited_body(self.request([b'abcd', b'efghi', b'not-consumed']), 8, detail=DETAIL)
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(caught.exception.detail, DETAIL)
        self.assertEqual(self.seen, [0, 1])

    async def test_limits_bytes_not_unicode_characters(self):
        with self.assertRaises(HTTPException):
            await read_limited_body(self.request(['你好'.encode()]), 5, detail=DETAIL)

    async def test_empty_body_at_zero_limit(self):
        self.assertEqual(await read_limited_body(self.request([b'']), 0, detail=DETAIL), b'')

    async def test_stream_failure_is_not_masked(self):
        async def stream():
            yield b'first'
            raise RuntimeError('synthetic disconnect')
        with self.assertRaisesRegex(RuntimeError, 'synthetic disconnect'):
            await read_limited_body(SimpleNamespace(stream=stream), 100, detail=DETAIL)
