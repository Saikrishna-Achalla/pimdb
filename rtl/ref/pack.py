#!/usr/bin/env python3
"""Storage format of the PIM tables (rtl/PLAN.md F4, F5): how a column's records sit in 32 B words.

Row group g = records [4096 g, 4096 g + 4096), on channel g mod 24. Bank b of that group holds records
4096 g + 256 b .. 4096 g + 256 b + 255 (record r = 0..255 inside the bank). A column of width w bits occupies
w words of the bank's DRAM row (256 records x w bits / 256 bits per word), starting at word address w0, which must be
a multiple of w (words), so that the slot = w0 + j mod w = j (tpch/bare.py's tile map meets this). Word j holds records j*n .. j*n + n - 1 (n = 256 / w); record
j*n + i is lane i, bits [i*w, i*w + w), two's complement, little-endian inside the lane. Byte k = bits [8k, 8k+8).
"""
import numpy as np

W = 256


def bank_records(g, b):
    s = 4096 * g + 256 * b
    return s, s + 256


def words(values, w):
    """values: 256 ints (signed) of one bank's records -> list of w words (Python ints, 256 bits each)."""
    n = W // w
    assert len(values) == 256
    mask = (1 << w) - 1
    out = []
    for j in range(w):
        word = 0
        for i in range(n):
            word |= (int(values[j * n + i]) & mask) << (i * w)
        out.append(word)
    return out


def bound(v, w):
    """A bound value repeated across 64 bits at width w (host-side PWGB format, rtl/PLAN.md F15)."""
    mask = (1 << w) - 1
    out = 0
    for i in range(64 // w):
        out |= (int(v) & mask) << (i * w)
    return out


def bounds_word(lo, hi, w, sgn, inv, mop):
    size = {8: 0, 16: 1, 32: 2, 64: 3}[w]
    cfg = size | (sgn << 2) | (inv << 3) | (mop << 4)
    return bound(lo, w) | (bound(hi, w) << 64) | (cfg << 128)


def column(arr, g, b, pad=0):
    s, e = bank_records(g, b)
    v = np.full(256, pad, dtype=np.int64)
    part = arr[s:min(e, len(arr))]
    v[:len(part)] = part
    return v
