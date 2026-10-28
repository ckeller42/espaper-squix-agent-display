"""Round-trip payloads through a transcription of the firmware's decode loop.

`pack_screen` and `unpack_screen` were written from the same understanding of
the format, so they can agree and both be wrong. `decode_payload` is read from
the C, so agreeing with it is evidence about the device.

What this does and does not pin: the bit layout is proven against the
transcribed loop. The palette direction (0 = black, 1 = white) comes from the
sketch's `palette[] = {MINI_BLACK, MINI_WHITE}`, not from that function, so it
still rests on having read the sketch correctly.
"""

import pytest
from PIL import Image

from espaper_server.packer import SCREEN_HEIGHT, SCREEN_WIDTH, pack_screen
from espaper_server.render import render
from tests.firmware_decode import decode_payload
from tests.recipes import FIXED_NOW, READINGS, RECIPE


@pytest.fixture
def sample_image() -> Image.Image:
    # Asymmetric on purpose: a flipped axis, an inverted palette or a bit-order
    # swap each change at least one of these pixels. (296 is a multiple of 8, so
    # row padding and the per-row bitCounter reset are not exercised here.)
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


def assert_round_trip(image, payload):
    # Literals, not imported constants: an independent check must not depend on
    # the values it is checking.
    assert len(payload) == 6 + 128 * 37  # 4742
    decoded = decode_payload(payload)
    assert decoded.size == (296, 128)
    assert list(decoded.get_flattened_data()) == list(image.get_flattened_data())


def test_round_trip_is_pixel_identical(sample_image):
    assert_round_trip(sample_image, pack_screen(sample_image))


def test_round_trip_holds_for_a_real_render():
    img = render(RECIPE, READINGS, FIXED_NOW)
    assert_round_trip(img, pack_screen(img))


def test_a_truncated_payload_is_not_accepted_as_a_round_trip():
    # The real render ends in white margin, and the firmware reuses its last
    # byte when the file runs short, so a short write decodes pixel-identical.
    img = render(RECIPE, READINGS, FIXED_NOW)
    with pytest.raises(AssertionError):
        assert_round_trip(img, pack_screen(img)[:-37])
