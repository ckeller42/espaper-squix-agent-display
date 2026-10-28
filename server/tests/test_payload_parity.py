"""Round-trip payloads through a transcription of the firmware's decode loop.

`pack_screen` and `unpack_screen` were written from the same understanding of
the format, so they can agree and both be wrong. `decode_payload` is read from
the C, so agreeing with it is evidence about the device.
"""

import pytest
from PIL import Image

from espaper_server.packer import SCREEN_HEIGHT, SCREEN_WIDTH, pack_screen
from espaper_server.render import render
from tests.firmware_decode import decode_payload
from tests.recipes import FIXED_NOW, READINGS, RECIPE


@pytest.fixture
def sample_image() -> Image.Image:
    # Asymmetric on purpose: a flipped axis, an inverted palette or a shifted
    # row boundary all change at least one of these pixels.
    img = Image.new("1", (SCREEN_WIDTH, SCREEN_HEIGHT), 1)
    for x in range(SCREEN_WIDTH):
        img.putpixel((x, x % SCREEN_HEIGHT), 0)
    img.putpixel((0, 0), 0)
    img.putpixel((SCREEN_WIDTH - 1, 0), 0)
    img.putpixel((SCREEN_WIDTH - 1, SCREEN_HEIGHT - 1), 0)
    img.putpixel((1, 5), 1)
    return img


def test_decode_rejects_a_bit_depth_the_device_would_refuse():
    # The device logs and returns WITHOUT drawing, leaving the old image up.
    bad = bytes([1, 4]) + (296).to_bytes(2, "big") + (128).to_bytes(2, "big") + b"\x00" * 4736
    with pytest.raises(ValueError):
        decode_payload(bad)


def test_round_trip_is_pixel_identical(sample_image):
    assert list(decode_payload(pack_screen(sample_image)).get_flattened_data()) == list(sample_image.get_flattened_data())


def test_round_trip_holds_for_a_real_render():
    img = render(RECIPE, READINGS, FIXED_NOW)
    assert list(decode_payload(pack_screen(img)).get_flattened_data()) == list(img.get_flattened_data())
