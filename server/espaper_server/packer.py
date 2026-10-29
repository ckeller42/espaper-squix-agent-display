"""Pack a 1-bit image into the screen payload read by MiniGrafx.

Layout (see lib/MiniGrafx drawPalettedBitmapFromFile): a 6-byte header
(version, bitsPerPixel, width BE16, height BE16) followed by row-major pixel
bits, MSB first, each row starting on a fresh byte.

The firmware palette is {BLACK, WHITE}, so bit 0 is black and bit 1 is white.
"""

from PIL import Image

SCREEN_WIDTH = 296
SCREEN_HEIGHT = 128
ROW_BYTES = (SCREEN_WIDTH + 7) // 8
HEADER_SIZE = 6
PAYLOAD_SIZE = HEADER_SIZE + ROW_BYTES * SCREEN_HEIGHT
VERSION = 1


HEADER = bytes([VERSION, 1]) + SCREEN_WIDTH.to_bytes(2, "big") + SCREEN_HEIGHT.to_bytes(2, "big")


def is_valid_payload(data: bytes) -> bool:
    """True when data is exactly one screen: the right length and the 6-byte header."""
    return len(data) == PAYLOAD_SIZE and data[:HEADER_SIZE] == HEADER


def pack_screen(image: Image.Image) -> bytes:
    if image.mode != "1" or image.size != (SCREEN_WIDTH, SCREEN_HEIGHT):
        raise ValueError(
            f"expected a 1-bit {SCREEN_WIDTH}x{SCREEN_HEIGHT} image, "
            f"got mode {image.mode!r} size {image.size}"
        )
    # PIL mode "1" raw rows are already MSB-first, byte-padded per row, 1 = white.
    return HEADER + image.tobytes()


def unpack_screen(data: bytes) -> Image.Image:
    """The inverse of pack_screen: the exact image a payload puts on the panel."""
    if not is_valid_payload(data):
        raise ValueError(f"not a {SCREEN_WIDTH}x{SCREEN_HEIGHT} 1-bit screen payload of {PAYLOAD_SIZE} bytes")
    return Image.frombytes("1", (SCREEN_WIDTH, SCREEN_HEIGHT), data[HEADER_SIZE:])
