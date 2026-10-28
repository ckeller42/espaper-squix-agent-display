import pytest
from PIL import Image

from espaper_server.packer import PAYLOAD_SIZE, SCREEN_HEIGHT, SCREEN_WIDTH, pack_screen


def blank_white_image() -> Image.Image:
    return Image.new("1", (SCREEN_WIDTH, SCREEN_HEIGHT), 1)


def blank_black_image() -> Image.Image:
    return Image.new("1", (SCREEN_WIDTH, SCREEN_HEIGHT), 0)


def test_payload_is_exactly_4742_bytes():
    assert len(pack_screen(blank_white_image())) == PAYLOAD_SIZE


def test_header_encodes_bit_depth_and_dimensions_big_endian():
    header = pack_screen(blank_white_image())[:6]
    assert header[1] == 1  # bitsPerPixel
    assert header[2:4] == (296).to_bytes(2, "big")
    assert header[4:6] == (128).to_bytes(2, "big")


def test_white_is_bit_one_black_is_bit_zero():
    # Palette index 0 is BLACK, 1 is WHITE -- inverted from "1 = ink".
    assert pack_screen(blank_white_image())[6:] == b"\xff" * (128 * 37)
    assert pack_screen(blank_black_image())[6:] == b"\x00" * (128 * 37)


def test_each_row_starts_on_a_fresh_byte():
    # One black pixel at (0, 1) must clear the MSB of row 1's first byte,
    # which is byte 37 of the pixel data -- not a continuation of row 0.
    img = blank_white_image()
    img.putpixel((0, 1), 0)
    data = pack_screen(img)[6:]
    assert data[37] == 0x7F
    assert data[36] == 0xFF


def test_rejects_wrong_dimensions():
    with pytest.raises(ValueError):
        pack_screen(Image.new("1", (200, 100), 1))
