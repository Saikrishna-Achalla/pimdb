#!/usr/bin/env python3
"""Golden reference for one PU (one bank), written from rtl/PLAN.md section 4, independently of the RTL.

State: lo, hi (64 b), cfg (size, sign, inv, mask_op), M, M1, V (256 b each). Words are Python ints, bit i = bit i of
the 256-bit word; lane i of width w is bits [i*w, i*w+w). Mask bit b = record b of the 256-record row group.

Commands (dicts): op in NOP, PWGB(gb, gbidx; only word 0 loads bounds + config), PCMP(x, addr), PLD_ROW(x), PLD_GB(gb), PCC(x, addr, cc), PSEL(x, addr),
PMC(dst, src, inv, mop), PRD -> returns M.
"""
W = 256
ALL = (1 << W) - 1
SIZES = {0: 8, 1: 16, 2: 32, 3: 64}
SET, AND, OR = 0, 1, 2


def lanes(word, w):
    return [(word >> (i * w)) & ((1 << w) - 1) for i in range(W // w)]


def to_signed(v, w):
    return v - (1 << w) if v >> (w - 1) else v


class PU:
    def __init__(self, join=True, setsel=True):
        self.join, self.setsel = join, setsel                # HAS_JOIN / HAS_SETSEL: absent commands do nothing
        self.lo = self.hi = 0
        self.size, self.sgn, self.inv, self.mop = 0, 0, 0, SET
        self.M = self.M1 = self.V = 0

    # --- helpers
    def _bound(self, b, i, w):
        """Lane i's bound at width w: bits (i*w mod 64) .. of the 64-bit bound (the host repeats the value)."""
        return (b >> ((i * w) % 64)) & ((1 << w) - 1)

    def _val(self, v, w):
        return to_signed(v, w) if self.sgn else v

    def _place(self, R, addr, n):
        """Slot placement + mask op on the window: R = list of n result bits."""
        slot = addr % (W // n)
        new = 0
        for r, b in enumerate(R):
            new |= (b & 1) << (slot * n + r)
        win = ((1 << n) - 1) << (slot * n)
        old = self.M & win
        if self.mop == SET:
            res = new
        elif self.mop == AND:
            res = old & new
        elif self.mop == OR:
            res = old | new
        else:
            res = old                                    # mop 3: reserved, M unchanged
        self.M = (self.M & ~win & ALL) | res

    # --- commands
    def step(self, c):
        op = c["op"]
        if op in ("PLD_ROW", "PLD_GB", "PCC", "PSEL", "PMC") and not self.join:
            return None
        if op == "PSEL" and not self.setsel:
            return None
        if op == "PWGB" and c.get("gbidx", 0) != 0:
            return None                                      # a set word: bounds and config unchanged
        if op == "PWGB":
            gb = c["gb"]
            self.lo = gb & ((1 << 64) - 1)
            self.hi = (gb >> 64) & ((1 << 64) - 1)
            cfg = (gb >> 128) & 0x3F
            self.size, self.sgn, self.inv, self.mop = cfg & 3, (cfg >> 2) & 1, (cfg >> 3) & 1, (cfg >> 4) & 3
        elif op == "PCMP":
            w = SIZES[self.size]
            R = []
            for i, x in enumerate(lanes(c["x"], w)):
                lo = self._val(self._bound(self.lo, i, w), w)
                hi = self._val(self._bound(self.hi, i, w), w)
                R.append(int(lo <= self._val(x, w) <= hi) ^ self.inv)
            self._place(R, c["addr"], W // w)
        elif op == "PLD_ROW":
            self.V = c["x"]
        elif op == "PLD_GB":
            self.V = c["gb"]
        elif op == "PCC":
            w = SIZES[self.size]
            L, E, G = (c["cc"] >> 2) & 1, (c["cc"] >> 1) & 1, c["cc"] & 1
            R = []
            for x, v in zip(lanes(c["x"], w), lanes(self.V, w)):
                a, b = self._val(x, w), self._val(v, w)
                R.append(int((L and a < b) or (E and a == b) or (G and a > b)))
            self._place(R, c["addr"], W // w)
        elif op == "PSEL":
            R = [((self.V >> x) & 1) ^ self.inv for x in lanes(c["x"], 8)]
            self._place(R, c["addr"], 32)
        elif op == "PMC":
            if c["src"] == 3 or c["mop"] == 3:
                return None                                  # no write
            src = {0: self.M, 1: self.M1, 2: self.V}[c["src"]]
            if c["inv"]:
                src = ~src & ALL
            dst = self.M if c["dst"] == 0 else self.M1
            dst = {SET: src, AND: dst & src, OR: dst | src}.get(c["mop"], dst)
            if c["dst"] == 0:
                self.M = dst
            else:
                self.M1 = dst
        elif op == "PRD":
            return self.M
        return None
