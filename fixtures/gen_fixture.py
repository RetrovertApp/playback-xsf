#!/usr/bin/env python3
"""Generate the self-authored playback fixture retrovert_selftest.gsf.

A GSF is a PSF container around a Game Boy Advance program, and this
writes that program in ARM directly: it opens the APU, points square
channel 1 at a four-note figure and walks it in a loop. GSF is the one
xSF flavour with no BIOS requirement, which is why the fixture is a GSF
rather than the PSF the planning asset assumed.

Deterministic apart from the zlib stream, which the PSF container
requires; the committed fixture and its sha256 in harness.toml must
match what this script emits.
"""

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).parent / "retrovert_selftest.gsf"

PSF_VERSION_GSF = 0x22
LOAD = 0x02000000  # EWRAM: an entry point here puts the emulator in multiboot mode

# GBA I/O registers, as offsets from 0x04000000.
SOUND1CNT_L, SOUND1CNT_H, SOUND1CNT_X = 0x60, 0x62, 0x64
SOUNDCNT_L, SOUNDCNT_H, SOUNDCNT_X = 0x80, 0x82, 0x84

# Square-wave rate is 131072 / (2048 - x), and bit 15 restarts the note.
FIGURE = [523.25, 659.26, 783.99, 1046.50]  # C5 E5 G5 C6
DELAY = 0x200000  # busy-loop iterations between notes, roughly a third of a second

AL = 0xE  # condition code "always"
MOV, ORR, ADD, SUB, AND = 13, 12, 4, 2, 0


def rotated_imm(value):
    """ARM data-processing immediates are an 8-bit value rotated right."""
    for rot in range(16):
        shift = rot * 2
        rotated = ((value << shift) | (value >> (32 - shift))) & 0xFFFFFFFF if shift else value
        if rotated < 0x100:
            return (rot << 8) | rotated
    raise ValueError(f"{value:#x} is not an ARM immediate")


def dp(opcode, rd, rn, imm, set_flags=0):
    return (AL << 28) | (1 << 25) | (opcode << 21) | (set_flags << 20) | (rn << 16) | (rd << 12) | rotated_imm(imm)


def strh(rd, rn, offset):
    return ((AL << 28) | (1 << 24) | (1 << 23) | (1 << 22) | (rn << 16) | (rd << 12)
            | ((offset >> 4) << 8) | (0xB << 4) | (offset & 0xF))


def ldr_scaled(rd, rn, rm, shift):
    return (AL << 28) | (3 << 25) | (1 << 24) | (1 << 23) | (1 << 20) | (rn << 16) | (rd << 12) | (shift << 7) | rm


def branch(cond, here, target):
    return (cond << 28) | (0xA << 24) | (((target - (here + 8)) >> 2) & 0xFFFFFF)


def note_word(hz):
    return 0x8000 | (2048 - round(131072 / hz))


def program():
    # Offsets are fixed by construction; the two branches and the table
    # address below depend on them, so keep the two lists in step.
    next_note = 0x3C
    delay_loop = 0x4C
    table = 0x5C

    code = [
        dp(MOV, 0, 0, 0x04000000),      # r0 = I/O base
        dp(MOV, 1, 0, 0x80),
        strh(1, 0, SOUNDCNT_X),         # master sound enable
        dp(MOV, 1, 0, 0x1100),
        dp(ORR, 1, 1, 0x77),
        strh(1, 0, SOUNDCNT_L),         # channel 1 to both sides, full volume
        dp(MOV, 1, 0, 0x02),
        strh(1, 0, SOUNDCNT_H),         # PSG output at 100%
        dp(MOV, 1, 0, 0x00),
        strh(1, 0, SOUND1CNT_L),        # no frequency sweep
        dp(MOV, 1, 0, 0xF000),
        dp(ORR, 1, 1, 0x80),
        strh(1, 0, SOUND1CNT_H),        # 50% duty, volume 15, envelope off
        dp(ADD, 2, 15, table - (0x34 + 8)),  # r2 = note table
        dp(MOV, 3, 0, 0),               # r3 = note counter
        # next_note:
        dp(AND, 4, 3, 3),
        ldr_scaled(5, 2, 4, 2),
        strh(5, 0, SOUND1CNT_X),        # frequency + restart
        dp(MOV, 6, 0, DELAY),
        # delay_loop:
        dp(SUB, 6, 6, 1, set_flags=1),
        branch(0x1, delay_loop + 4, delay_loop),  # BNE delay_loop
        dp(ADD, 3, 3, 1),
        branch(AL, delay_loop + 12, next_note),   # B next_note
    ]
    assert len(code) * 4 == table, (len(code) * 4, table)
    code += [note_word(hz) for hz in FIGURE]
    return b"".join(struct.pack("<I", word) for word in code)


def build():
    rom = program()
    # The GSF program section is a 12-byte header followed by the image.
    exe = struct.pack("<III", LOAD, LOAD, len(rom)) + rom
    compressed = zlib.compress(exe, 9)
    header = struct.pack(
        "<3sBIII", b"PSF", PSF_VERSION_GSF, 0, len(compressed), zlib.crc32(compressed) & 0xFFFFFFFF
    )
    tags = b"[TAG]title=Retrovert self-test\nartist=Retrovert\n"
    return header + compressed + tags


def main():
    data = build()
    OUT.write_bytes(data)
    print(f"wrote {OUT} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
