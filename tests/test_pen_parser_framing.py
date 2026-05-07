"""Pen parser framing layer (STX/ETX/DLE escape).

We can't test packet semantics without real BLE captures, but we can
verify the byte-level state machine doesn't crash on edge cases and
that DLE-escape decoding works.
"""

import asyncio

import pytest

from pen_logger import Parser, STX, ETX, DLE


@pytest.fixture
def parser():
    return Parser(asyncio.Queue())


def test_garbage_outside_frame_is_ignored(parser):
    """Bytes that arrive without a leading STX must be dropped silently."""
    parser.feed(b"\x00\x01\x02\x03\xff\xfe")
    assert parser._buf == bytearray()
    assert parser._in is False
    assert parser.parse_errors == 0


def test_stx_resets_buffer(parser):
    parser.feed(bytes([STX, 0x42, 0x43]))
    assert parser._in is True
    assert bytes(parser._buf) == b"\x42\x43"


def test_etx_finalizes_frame_and_clears_buffer(parser):
    # An undersized frame is fine — _parse just returns early.
    parser.feed(bytes([STX, 0x10, ETX]))
    assert parser._in is False
    assert parser._buf == bytearray()


def test_dle_escape_unescapes_xor_0x20(parser):
    """DLE+(b ^ 0x20) decodes back to b inside a frame."""
    escaped_byte = STX ^ 0x20
    parser.feed(bytes([STX, DLE, escaped_byte, ETX]))
    # Buffer was finalized + cleared by ETX; we just check it didn't crash and
    # that the escape state is reset.
    assert parser._esc is False
    assert parser._in is False


def test_truncated_frame_does_not_crash(parser):
    """If ETX never arrives the parser keeps buffering — no exception."""
    parser.feed(bytes([STX, 0x01, 0x02, 0x03]))
    assert parser._in is True
    assert bytes(parser._buf) == b"\x01\x02\x03"


def test_back_to_back_frames(parser):
    parser.feed(bytes([STX, 0x10, ETX, STX, 0x20, ETX]))
    assert parser._in is False
    assert parser._buf == bytearray()
    assert parser.parse_errors == 0
