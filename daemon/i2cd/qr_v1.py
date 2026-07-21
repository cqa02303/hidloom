"""Small dependency-free QR Code Version 1-L alphanumeric encoder.

This deliberately implements only the profile used by the 64 px OLED.  Keeping
the accepted alphabet and capacity narrow makes an oversized or ambiguous
management URL fail closed instead of silently changing the rendered symbol.
"""
from __future__ import annotations

ALPHANUMERIC = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
SIZE = 21
MAX_CHARS = 25
DATA_CODEWORDS = 19
ECC_CODEWORDS = 7


def encode_v1_l(text: str) -> tuple[tuple[bool, ...], ...]:
    """Encode up to 25 QR-alphanumeric characters as Version 1-L, mask 0."""
    if not isinstance(text, str) or not text or len(text) > MAX_CHARS:
        raise ValueError(f"QR Version 1-L text must contain 1..{MAX_CHARS} characters")
    try:
        values = [ALPHANUMERIC.index(char) for char in text]
    except ValueError as exc:
        raise ValueError("QR Version 1-L text contains a non-alphanumeric character") from exc

    bits: list[int] = []
    _append_bits(bits, 0b0010, 4)  # alphanumeric mode
    _append_bits(bits, len(values), 9)
    for index in range(0, len(values) - 1, 2):
        _append_bits(bits, values[index] * 45 + values[index + 1], 11)
    if len(values) % 2:
        _append_bits(bits, values[-1], 6)
    capacity = DATA_CODEWORDS * 8
    bits.extend([0] * min(4, capacity - len(bits)))
    bits.extend([0] * ((-len(bits)) % 8))
    data = [_bits_to_int(bits[index:index + 8]) for index in range(0, len(bits), 8)]
    for pad in (0xEC, 0x11) * DATA_CODEWORDS:
        if len(data) >= DATA_CODEWORDS:
            break
        data.append(pad)
    codewords = data + _reed_solomon_remainder(data, ECC_CODEWORDS)
    return _draw_matrix(codewords)


def scaled_pixels(
    matrix: tuple[tuple[bool, ...], ...], *, scale: int = 2, quiet_modules: int = 4
) -> tuple[tuple[bool, ...], ...]:
    """Return a scaled symbol including the QR-required four-module quiet zone."""
    if len(matrix) != SIZE or any(len(row) != SIZE for row in matrix):
        raise ValueError("QR matrix must be 21x21")
    if scale < 1 or quiet_modules < 4:
        raise ValueError("QR scale must be positive and quiet zone must be at least 4 modules")
    width = (SIZE + quiet_modules * 2) * scale
    pixels = [[False] * width for _ in range(width)]
    offset = quiet_modules * scale
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if not dark:
                continue
            for dy in range(scale):
                for dx in range(scale):
                    pixels[offset + y * scale + dy][offset + x * scale + dx] = True
    return tuple(tuple(row) for row in pixels)


def _append_bits(target: list[int], value: int, count: int) -> None:
    target.extend((value >> shift) & 1 for shift in range(count - 1, -1, -1))


def _bits_to_int(bits: list[int]) -> int:
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    return value


def _gf_multiply(left: int, right: int) -> int:
    result = 0
    for _ in range(8):
        if right & 1:
            result ^= left
        right >>= 1
        left = (left << 1) ^ (0x11D if left & 0x80 else 0)
    return result


def _reed_solomon_remainder(data: list[int], degree: int) -> list[int]:
    generator = [1]
    root = 1
    for _ in range(degree):
        next_generator = [0] * (len(generator) + 1)
        for index, coefficient in enumerate(generator):
            next_generator[index] ^= coefficient
            next_generator[index + 1] ^= _gf_multiply(coefficient, root)
        generator = next_generator
        root = _gf_multiply(root, 2)
    remainder = [0] * degree
    for value in data:
        factor = value ^ remainder[0]
        remainder = remainder[1:] + [0]
        for index in range(degree):
            remainder[index] ^= _gf_multiply(generator[index + 1], factor)
    return remainder


def _draw_matrix(codewords: list[int]) -> tuple[tuple[bool, ...], ...]:
    modules = [[False] * SIZE for _ in range(SIZE)]
    function = [[False] * SIZE for _ in range(SIZE)]

    def set_function(x: int, y: int, dark: bool) -> None:
        if 0 <= x < SIZE and 0 <= y < SIZE:
            modules[y][x] = dark
            function[y][x] = True

    def finder(cx: int, cy: int) -> None:
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                distance = max(abs(dx), abs(dy))
                set_function(cx + dx, cy + dy, distance not in {2, 4})

    finder(3, 3)
    finder(SIZE - 4, 3)
    finder(3, SIZE - 4)
    for index in range(8, SIZE - 8):
        set_function(index, 6, index % 2 == 0)
        set_function(6, index, index % 2 == 0)

    # Reserve both format-information strips before placing data.
    for index in range(0, 6):
        function[index][8] = True
    function[7][8] = function[8][8] = function[8][7] = True
    for index in range(9, 15):
        function[14 - index][8] = True
    for index in range(0, 8):
        function[8][SIZE - 1 - index] = True
    for index in range(8, 15):
        function[SIZE - 15 + index][8] = True
    set_function(8, SIZE - 8, True)

    data_bits = [(value >> shift) & 1 for value in codewords for shift in range(7, -1, -1)]
    bit_index = 0
    right = SIZE - 1
    upward = True
    while right >= 1:
        if right == 6:
            right -= 1
        rows = range(SIZE - 1, -1, -1) if upward else range(SIZE)
        for y in rows:
            for x in (right, right - 1):
                if function[y][x]:
                    continue
                bit = data_bits[bit_index] if bit_index < len(data_bits) else 0
                bit_index += 1
                modules[y][x] = bool(bit ^ ((x + y) % 2 == 0))  # mask 0
        upward = not upward
        right -= 2

    # Error-correction level L is binary 01; use mask pattern 0.
    format_data = 0b01 << 3
    remainder = format_data
    for _ in range(10):
        remainder = (remainder << 1) ^ (0x537 if remainder >> 9 else 0)
    format_bits = ((format_data << 10) | remainder) ^ 0x5412
    for index in range(15):
        dark = bool((format_bits >> index) & 1)
        first = ((8, index) if index < 6 else
                 (8, 7) if index == 6 else
                 (8, 8) if index == 7 else
                 (7, 8) if index == 8 else
                 (14 - index, 8))
        second = ((SIZE - 1 - index, 8) if index < 8 else
                  (8, SIZE - 15 + index))
        set_function(*first, dark)
        set_function(*second, dark)
    set_function(8, SIZE - 8, True)
    return tuple(tuple(row) for row in modules)
