"""Literal transcription of MiniGrafx::drawPalettedBitmapFromFile.

Source: lib/MiniGrafx/src/MiniGrafx.cpp, lines 1011-1077. Line numbers below
refer to that file. Written from the C, deliberately not from packer.py, so it
is an independent reading of the format. Keep it literal; do not tidy it.

Instead of setColor()/setPixel() onto the e-paper buffer, the palette index is
stored as a pixel of a mode "1" image. The firmware's palette maps index 0 to
black and 1 to white, which is also what mode "1" values 0 and 1 mean.
"""

from PIL import Image

# The device is configured with 1 bit per pixel (a two-colour e-paper panel).
BITS_PER_PIXEL = 1


def decode_payload(data: bytes) -> Image.Image:
    bitsPerPixel = BITS_PER_PIXEL
    bitMask = (1 << bitsPerPixel) - 1  # :74
    pixelsPerByte = 8 // bitsPerPixel  # :75

    # :1021-1022 file.readBytes(buf, 6); fileSize -= 6;
    buf = bytearray(data[:6])
    fileSize = len(data) - 6
    pos = 6  # file read cursor

    # :1024
    bmpBitDepth = buf[1]

    # :1027-1030 the device logs and returns without drawing.
    if bmpBitDepth != bitsPerPixel:
        raise ValueError(f"Bmp has wrong bit depth. Device: {bitsPerPixel}, bmp: {bmpBitDepth}")

    # :1032-1033
    width = buf[2] << 8 | buf[3]
    height = buf[4] << 8 | buf[5]

    image = Image.new("1", (width, height))

    # :1040-1041
    paletteIndex = 0
    data_byte = 0
    # :1047 shift = 8 - bitsPerPixel;
    shift = 8 - bitsPerPixel
    # :1049
    bitCounter = 0

    # :1051
    for y in range(height):
        # :1052
        for x in range(width):
            # :1054
            if bitCounter == pixelsPerByte or bitCounter == 0:
                # :1055-1058 file.readBytes(buf, 1); fileSize--;
                if fileSize > 0:
                    buf[0] = data[pos]
                    pos += 1
                    fileSize -= 1

                # :1060 (on a short read the C reuses the stale buf[0])
                data_byte = buf[0]
                # :1063
                bitCounter = 0
            # :1065
            shift = 8 - (bitCounter + 1) * bitsPerPixel
            # :1066
            paletteIndex = (data_byte >> shift) & bitMask

            # :1069-1070 setColor(paletteIndex); setPixel(x, y);
            image.putpixel((x, y), paletteIndex)
            # :1071
            bitCounter += 1
        # :1075 bitCounter = 0 at the end of each row
        bitCounter = 0

    return image
