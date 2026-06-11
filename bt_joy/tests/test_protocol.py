import struct
import unittest
import zlib

from bt_joy.protocol import (
    is_keepalive_request,
    is_keepalive_response,
    pack_frame,
    pack_keepalive_request,
    pack_keepalive_response,
    unpack_frame,
    unpack_keepalive_request,
    unpack_keepalive_response,
)


class ProtocolTest(unittest.TestCase):
    def test_pack_and_unpack_frame(self) -> None:
        frame = pack_frame([1000, 1500, 2000], sequence=42, timestamp=123456)

        sequence, timestamp, channels = unpack_frame(frame)

        self.assertEqual(sequence, 42)
        self.assertEqual(timestamp, 123456)
        self.assertEqual(channels, [1000, 1500, 2000])

    def test_rejects_bad_crc(self) -> None:
        frame = bytearray(pack_frame([1500], sequence=1, timestamp=2))
        frame[-1] ^= 0xFF

        with self.assertRaises(ValueError):
            unpack_frame(bytes(frame))

    def test_pack_and_unpack_keepalive_request(self) -> None:
        frame = pack_keepalive_request(sequence=7, timestamp=1000)

        sequence, timestamp = unpack_keepalive_request(frame)

        self.assertTrue(is_keepalive_request(frame))
        self.assertFalse(is_keepalive_response(frame))
        self.assertEqual(sequence, 7)
        self.assertEqual(timestamp, 1000)

    def test_pack_and_unpack_keepalive_response(self) -> None:
        frame = pack_keepalive_response(sequence=7, client_sent_at=1000, server_received_at=1250)

        sequence, client_sent_at, server_received_at, delay_us = unpack_keepalive_response(frame)

        self.assertFalse(is_keepalive_request(frame))
        self.assertTrue(is_keepalive_response(frame))
        self.assertEqual(sequence, 7)
        self.assertEqual(client_sent_at, 1000)
        self.assertEqual(server_received_at, 1250)
        self.assertEqual(delay_us, 250)

    def test_keepalive_request_rejects_wrong_size(self) -> None:
        body = struct.pack("<4sBIQH", b"BTKA", 1, 7, 1000, 0)
        crc = struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)

        with self.assertRaises(ValueError):
            unpack_keepalive_request(body + crc)


if __name__ == "__main__":
    unittest.main()
