#!/usr/bin/env python3
"""Fail if a firmware image was linked without room for its filesystem.

This exists because the device told us nothing. `board_build.ldscript` lived in
the `[esp8266]` section, which no `[env:...]` ever referenced, so the linker
quietly used the board default -- a 2MB layout with a ZERO-byte filesystem. The
firmware then formatted the filesystem on every boot, failed every write, and
could never store its configuration, while the build reported SUCCESS and the
ldscript line in platformio.ini read exactly right.

A linker symbol is the only place that mismatch is visible, so the check reads
the symbols out of the ELF. The xtensa toolchain's nm is x86_64-only and the
build Macs are arm64 without Rosetta, so the symbol table is parsed here rather
than shelled out to.
"""

import struct
import sys

# Flash is mapped at this address on the ESP8266, so a symbol minus this is the
# offset esptool would write to.
FLASH_MAP_BASE = 0x40200000
SHT_SYMTAB = 2
WANTED = ("_FS_start", "_FS_end", "_FS_page", "_FS_block")


def read_symbols(path, names):
    data = open(path, "rb").read()
    if data[:4] != b"\x7fELF":
        raise SystemExit(f"{path}: not an ELF file")
    if data[4] != 1:
        raise SystemExit(f"{path}: expected a 32-bit ELF")
    endian = "<" if data[5] == 1 else ">"

    (section_offset,) = struct.unpack_from(endian + "I", data, 0x20)
    entry_size, count, _ = struct.unpack_from(endian + "HHH", data, 0x2E)

    sections = []
    for index in range(count):
        fields = struct.unpack_from(endian + "10I", data, section_offset + index * entry_size)
        sections.append(dict(type=fields[1], offset=fields[4], size=fields[5],
                             link=fields[6], entsize=fields[9]))

    def name_at(table, offset):
        raw = data[table["offset"] + offset:]
        return raw[:raw.index(b"\0")].decode()

    found = {}
    for section in sections:
        if section["type"] != SHT_SYMTAB or not section["entsize"]:
            continue
        strings = sections[section["link"]]
        for offset in range(section["offset"], section["offset"] + section["size"],
                            section["entsize"]):
            sym_name, sym_value = struct.unpack_from(endian + "II", data, offset)
            symbol = name_at(strings, sym_name)
            if symbol in names:
                found[symbol] = sym_value
    return found


def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: check-fs-region.py <firmware.elf>")
    path = argv[1]
    symbols = read_symbols(path, WANTED)

    missing = [name for name in ("_FS_start", "_FS_end") if name not in symbols]
    if missing:
        raise SystemExit(f"{path}: no {', '.join(missing)} symbol -- not an ESP8266 image?")

    start, end = symbols["_FS_start"], symbols["_FS_end"]
    size = end - start
    print(f"{path}")
    print(f"  _FS_start = {start:#010x}  (flash {start - FLASH_MAP_BASE:#08x})")
    print(f"  _FS_end   = {end:#010x}  (flash {end - FLASH_MAP_BASE:#08x})")
    print(f"  _FS_page  = {symbols.get('_FS_page', 0):#x}"
          f"   _FS_block = {symbols.get('_FS_block', 0):#x}")
    print(f"  size      = {size // 1024} KB")

    if size <= 0:
        raise SystemExit(
            "FAIL: the filesystem region is empty. The firmware will reformat on every\n"
            "      boot and every write will fail, so it can never store its config.\n"
            "      Check that the env references board_build.ldscript (a bare\n"
            "      [esp8266] section is inherited by nothing)."
        )
    # A page or block of zero mounts nothing even when the region has room.
    if not symbols.get("_FS_page") or not symbols.get("_FS_block"):
        raise SystemExit("FAIL: _FS_page or _FS_block is zero; LittleFS cannot mount.")
    print("OK: filesystem region is non-empty and its geometry is set.")


if __name__ == "__main__":
    main(sys.argv)
