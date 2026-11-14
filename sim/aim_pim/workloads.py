#!/usr/bin/env python3
"""Workload definitions (micro-suite + chains Q6/Q1) as chains of general DB-PU operators, each with an exact
check against DuckDB. A workload = layout + base data + (untimed) setup operators + timed operators."""
import math
import numpy as np
import dbpu as P
import data as D

I16MIN, I32MIN, I32MAX, I64MAX = -(1 << 15), -(1 << 31), (1 << 31) - 1, (1 << 63) - 1
D94, D95 = D.days(1994, 1, 1), D.days(1995, 1, 1)
Q1_DATE = D.days(1998, 9, 2)   # DATE '1998-12-01' - INTERVAL 90 DAY


class Workload:
    def __init__(self, name, layout, base, ops, check, setup=(), input_cols=None, mask_readout=None,
                 compact_readout=None, kind="operator", note=""):
        self.name, self.L, self.base, self.ops, self.check = name, layout, base, list(ops), check
        self.setup, self.mask_readout, self.compact_readout, self.kind, self.note = list(setup), mask_readout, compact_readout, kind, note
        cols = input_cols if input_cols is not None else list(layout.cols)
        self.input_bytes = layout.n * sum(layout.widths[c] for c in cols)


def _lay(n, cols, scratch=None, masks=1, ch=1):
    return P.Layout(n, cols, scratch, mask_slots=masks, n_channels=ch)


def _flat(pu, name, n):
    return pu.col[name].reshape(-1)[:n]


def _maskflat(pu, name, n):
    return pu.m(name).reshape(-1)[:n]


class CMPb8(P.CMP):
    """predicate with a 1-byte-per-record boolean output (cuDF's bool8) instead of the 1-bit mask."""
    def rowcmds(self, ctx, r):
        c = [x for x in super().rowcmds(ctx, r) if x[0] != "PWB"]
        return c + [("PWB", ctx.L.T // P.WORD_B)]


def micro(sf, d, ref):
    n = len(d["price"])
    W = []
    # 1 predicate -> mask (int32 date; 64-bit decimal; bool8 output variant; + GPU read-out of the bitmask)
    for var, readout in (("", None), ("+maskreadout", "M0")):
        L = _lay(n, {"ship": 4})
        W.append(Workload(f"pred_ship32{var}", L, {"ship": d["ship"]}, [P.CMP("ship", I32MIN, D94 - 1, store=True)],
                          lambda pu, L=L: np.array_equal(_maskflat(pu, "M0", n), ref["pred_ship"]), mask_readout=readout))
    L = _lay(n, {"ship": 4})
    W.append(Workload("pred_ship32_bool8out", L, {"ship": d["ship"]}, [CMPb8("ship", I32MIN, D94 - 1, store=True)],
                      lambda pu, L=L: np.array_equal(_maskflat(pu, "M0", n), ref["pred_ship"])))
    L = _lay(n, {"price64": 8})
    W.append(Workload("pred_price64", L, {"price64": d["price"].astype(np.int64)},
                      [P.CMP("price64", 5_000_001, I64MAX, store=True)],
                      lambda pu, L=L: np.array_equal(_maskflat(pu, "M0", n), ref["pred_price"])))
    # 2 range predicate AND range predicate (two columns) -> one mask
    L = _lay(n, {"ship": 4, "disc": 4})
    W.append(Workload("pred_and", L, {"ship": d["ship"], "disc": d["disc"]},
                      [P.CMP("ship", D94, D95 - 1), P.CMP("disc", 5, 7, comb="AND", store=True)],
                      lambda pu, L=L: np.array_equal(_maskflat(pu, "M0", n), ref["pred_and"])))
    # 3 compaction: mask (exists in the row) -> per-bank count + selected record ids (int32) in the bank
    for var, ro in (("", None), ("+readout", ("ids", 4))):
        L = _lay(n, {"ship": 4}, {"ids": 4})
        W.append(Workload(f"compact_ids{var}", L, {"ship": d["ship"]}, [P.COMPACT("ids", None, "M0", 4)],
                          lambda pu, L=L: (int(pu.cnt.sum()) == len(ref["compact_ids"]) and
                                           np.array_equal(np.sort(P.gather_compacted(pu, "ids")), ref["compact_ids"])),
                          setup=[P.CMP("ship", D94, D95 - 1)], input_cols=[], compact_readout=ro,
                          note="input = the existing 1-bit mask (n/8 B); the ship compare is untimed setup"))
        W[-1].input_bytes = n // 8
    # 5 element-wise: multiply two int32 columns -> int64 (written back); int64 x int64; widen int32 -> int64
    L = _lay(n, {"price": 4, "disc": 4}, {"prod": 8})
    W.append(Workload("ew_mul32x32", L, {"price": d["price"], "disc": d["disc"]}, [P.MUL("prod", "price", "disc")],
                      lambda pu, L=L: np.array_equal(_flat(pu, "prod", n), ref["mul"])))
    L = _lay(n, {"p64": 8, "d64": 8}, {"prod": 8})
    W.append(Workload("ew_mul64x64", L, {"p64": d["price"].astype(np.int64), "d64": d["disc"].astype(np.int64)},
                      [P.MUL("prod", "p64", "d64")], lambda pu, L=L: np.array_equal(_flat(pu, "prod", n), ref["mul"])))
    L = _lay(n, {"price": 4}, {"p64": 8})
    W.append(Workload("ew_widen32to64", L, {"price": d["price"]}, [P.EW("widen", "p64", "price")],
                      lambda pu, L=L: np.array_equal(_flat(pu, "p64", n), d["price"].astype(np.int64))))
    # 6 reduce: sum of an int32 column, of an int64 column
    L = _lay(n, {"price": 4})
    W.append(Workload("sum_int32", L, {"price": d["price"]}, [P.SUM("price")],
                      lambda pu: int(pu.acc.sum()) == int(ref["sum_price"])))
    L = _lay(n, {"p64": 8})
    W.append(Workload("sum_int64", L, {"p64": d["price"].astype(np.int64)}, [P.SUM("p64")],
                      lambda pu: int(pu.acc.sum()) == int(ref["sum_price"])))
    # 7 small-group aggregation: sum(qty), count(*) by a <= 8-group key (Q1 key: rf*2+ls, existing column)
    L = _lay(n, {"key": 1, "qty": 2})
    key = (d["rf"].astype(np.int8) * 2 + d["ls"]).astype(np.int8)

    def chk_g(pu):
        g = ref["gagg"]
        return all(int(pu.gacc["qty"][:, k].sum()) == int(sq) and int(pu.gacc["count"][:, k].sum()) == int(c)
                   for k, sq, c in g) and int(pu.gacc["count"].sum()) == n
    W.append(Workload("gagg_sum_count", L, {"key": key, "qty": d["qty"]}, [P.GAGG("key", ["qty"])], chk_g))
    # 8 membership of a column in a small key set (8 constants, OR of equality compares)
    L = _lay(n, {"qty": 2})
    keys = [1, 5, 10, 20, 30, 40, 45, 50]
    ops = [P.CMP("qty", k * 100, k * 100, comb="SET" if i == 0 else "OR", store=(i == 7)) for i, k in enumerate(keys)]
    W.append(Workload("member_in8", L, {"qty": d["qty"]}, ops,
                      lambda pu: int(_maskflat(pu, "M0", n).sum()) == int(ref["member"])))
    return W


def q6_chains(sf, d, ref, ch=1, n=None):
    n = n or len(d["price"])
    base = {k: d[k][:n] for k in ("ship", "disc", "qty", "price")}
    cols = {"ship": 4, "disc": 4, "qty": 2, "price": 4}
    pred = [P.CMP("ship", D94, D95 - 1), P.CMP("disc", 5, 7, comb="AND"), P.CMP("qty", I16MIN, 2399, comb="AND")]
    chk = (lambda pu: int(pu.acc.sum()) == int(ref["q6"])) if n == len(d["price"]) else (lambda pu: True)
    W = []
    L = _lay(n, cols, {"prod": 8}, ch=ch)
    W.append(Workload("q6_mulwb_sum", L, base, pred + [P.MUL("prod", "price", "disc"), P.SUM("prod", "M0")], chk, kind="chain",
                      note="variant: CMP,CMP(AND),CMP(AND) -> MUL price*disc written back to the row -> masked SUM (as Sirius: Mul kernel then reduce)"))
    L = _lay(n, cols, ch=ch)
    W.append(Workload("q6_main", L, base, pred + [P.MMAC("price", "disc", "M0")], chk, kind="chain",
                      note="MAIN: CMP,CMP(AND),CMP(AND) -> masked multiply-accumulate (4 general ops, unfused)"))
    L = _lay(n, cols, {"p64": 8, "d64": 8, "prod": 8}, ch=ch)
    W.append(Workload("q6_mirror_sirius", L, base,
                      pred + [P.EW("widen", "p64", "price"), P.EW("widen", "d64", "disc"), P.MUL("prod", "p64", "d64"),
                              P.SUM("prod", "M0")], chk, kind="chain",
                      note="as cuDF: 2 casts int32->int64, 64x64 multiply, masked sum (compaction+gathers replaced by the mask)"))
    return W


def q1_chain(sf, d, ref, ch=1, n=None):
    n = n or len(d["price"])
    cols = {"qty": 2, "price": 4, "disc": 4, "tax": 4, "ship": 4, "rf": 1, "ls": 1}
    base = {k: d[k][:n] for k in cols}
    L = _lay(n, cols, {"omd": 4, "dp": 8, "opt": 4, "charge": 8, "key": 1}, ch=ch)
    ops = [P.CMP("ship", I32MIN, Q1_DATE),
           P.EW("rsub_c", "omd", "disc", c=100),            # (1 - discount) x100
           P.MUL("dp", "price", "omd"),                     # disc_price, scale 4
           P.EW("add_c", "opt", "tax", c=100),              # (1 + tax) x100
           P.MUL("charge", "dp", "opt"),                    # charge, scale 6 (64x32)
           P.EW("add_shl", "key", "ls", "rf", s=1),          # group key = rf*2 + ls (composite-key packing)
           P.GAGG("key", ["qty", "price", "dp", "charge", "disc"], "M0", count=True)]

    def chk(pu):
        if n != len(d["price"]):
            return True
        ok = True
        for k, sq, sp, sd, sc, aq, ap, ad, cnt, sdisc in ref["q1"]:
            g = {a: int(pu.gacc[a][:, k].sum()) for a in ("qty", "price", "dp", "charge", "disc", "count")}
            ok &= (g["qty"], g["price"], g["dp"], g["charge"], g["count"], g["disc"]) == (sq, sp, sd, sc, cnt, sdisc)
            # averages are computed on the host from the exact sums (decimal(…,2) -> float compare)
            ok &= abs(g["qty"] / 100 / cnt - aq) <= 1e-9 * abs(aq) and abs(g["price"] / 100 / cnt - ap) <= 1e-9 * abs(ap)
            ok &= abs(g["disc"] / 100 / cnt - ad) <= 1e-9 * abs(ad)
        nz = sum(int(pu.gacc["count"][:, k].sum()) > 0 for k in range(8))
        return ok and nz == len(ref["q1"])
    return [Workload("q1_main", L, base, ops, chk, kind="chain",
                     note="CMP -> 1-disc -> MUL -> 1+tax -> MUL(64x32) -> key pack -> GAGG x5 + count; host sorts <=6 groups")]
