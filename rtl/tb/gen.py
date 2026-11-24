#!/usr/bin/env python3
"""Test vectors for tb_pu.sv: a command sequence, run on the golden model rtl/ref/pu_ref.py, written as hex files.

    gen.py random <name> [n=20000] [join=1] [setsel=1] [seed=1]
    gen.py replay <q6|q12la|q19la|q12join> [groups=0,1,777,14600]

Replays pack real SF10 columns (tpch/cache) with rtl/ref/pack.py and check every PRD word of the golden model against
the per-record bitmaps of the functional model (tpch/lookahead.bitmap), before the vectors are written.

Output rtl/tb/vec/<name>/: ctrl.hex (op[3:0] addr[9:4] cc[12:10] pmc_dst[13] pmc_src[15:14] pmc_inv[16]
pmc_op[18:17] prd[19] xrd[20] M/M1/V defined [23:21] PWGB to buffer word 0 [24]), x.hex, gb.hex, m.hex / m1.hex / v.hex (state after each
command), rd.hex (PRD result),
n.txt (number of commands).
"""
import os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ref"))
import pu_ref as R                                                    # noqa: E402
import pack as P                                                      # noqa: E402

OPS = dict(NOP=0, PWGB=1, PCMP=2, PLD_ROW=3, PLD_GB=4, PCC=5, PSEL=6, PMC=7, PRD=8)
READS = {"PCMP", "PLD_ROW", "PCC", "PSEL"}
W = 256
ALL = (1 << W) - 1


def cmd(op, **kw):
    c = dict(op=op, x=0, gb=0, addr=0, cc=0, dst=0, src=0, inv=0, mop=0)
    c.update(kw)
    return c


def write(name, cmds, join=True, setsel=True):
    out = os.path.join(HERE, "vec", name)
    os.makedirs(out, exist_ok=True)
    pu = R.PU(join, setsel)
    known = dict(M=False, M1=False, V=False)
    f = {k: open(os.path.join(out, k + ".hex"), "w") for k in ("ctrl", "x", "gb", "m", "m1", "v", "rd")}
    rd = []
    for c in cmds:
        r = pu.step(c)
        if c["op"] == "PRD":
            rd.append(r)
        # which state is defined (no reset in the RTL)
        if c["op"] in ("PLD_ROW", "PLD_GB") and join:
            known["V"] = True
        if c.get("m_defined"):
            known["M"] = True
        if c["op"] == "PMC" and c["src"] != 3 and c["mop"] != 3 and join:
            srcok = {0: known["M"], 1: known["M1"], 2: known["V"]}[c["src"]]
            d = "M" if c["dst"] == 0 else "M1"
            known[d] = srcok and (c["mop"] == 0 or known[d])
        ctrl = (OPS[c["op"]] | (c["addr"] << 4) | (c["cc"] << 10) | (c["dst"] << 13) | (c["src"] << 14)
                | (c["inv"] << 16) | (c["mop"] << 17) | (int(c["op"] == "PRD") << 19) | (int(c["op"] in READS) << 20)
                | (int(known["M"]) << 21) | (int(known["M1"]) << 22) | (int(known["V"]) << 23)
                | (int(c["op"] == "PWGB" and c.get("gbidx", 0) == 0) << 24))
        f["ctrl"].write(f"{ctrl:08x}\n")
        f["x"].write(f"{c['x']:064x}\n")
        f["gb"].write(f"{c['gb']:064x}\n")
        f["rd"].write(f"{r if r is not None else 0:064x}\n")
        for k, v in (("m", pu.M), ("m1", pu.M1), ("v", pu.V)):
            ok = known[{"m": "M", "m1": "M1", "v": "V"}[k]]
            f[k].write(f"{v if ok else 0:064x}\n")
    for h in f.values():
        h.close()
    open(os.path.join(out, "n.txt"), "w").write(f"{len(cmds)}\n")
    print(name, len(cmds), "commands,", len(rd), "PRDs ->", out)
    return rd


def init_m(cmds):
    """Define M without a reset: 8-bit SET over all 8 slots."""
    cmds.append(cmd("PWGB", gb=P.bounds_word(0, 0, 8, 0, 0, 0)))
    for j in range(8):
        cmds.append(cmd("PCMP", x=random.getrandbits(W), addr=j))
    cmds[-1]["m_defined"] = True


# ------------------------------------------------------------------ random
def near(base, w):
    """A w-bit value equal to base above a random byte k, random at byte k and below (exercises the byte tree)."""
    k = random.randrange(w // 8)
    hi_mask = ((1 << w) - 1) & ~((1 << (8 * k + 8)) - 1)
    v = (base & hi_mask) | random.getrandbits(8 * k + 8)
    if random.random() < 0.15:
        v = base
    return v & ((1 << w) - 1)


def lane_word(w, bases):
    word = 0
    for i in range(W // w):
        b = random.choice(bases + [random.getrandbits(w)])
        word |= near(b, w) << (i * w)
    return word


def rand_bound(w):
    s = random.random()
    m = (1 << w) - 1
    if s < 0.1:
        return random.choice([0, m, 1 << (w - 1), (1 << (w - 1)) - 1])
    return random.getrandbits(w)


def random_cmds(n, join, setsel):
    cmds = []
    init_m(cmds)
    if join:
        cmds.append(cmd("PLD_GB", gb=random.getrandbits(W)))
        cmds.append(cmd("PMC", dst=1, src=2, mop=0))
    st = dict(w=8, lo=0, hi=0, V=[0])
    ops = ["PWGB", "PCMP", "PCMP", "PCMP", "PRD", "NOP", "PLD_ROW", "PLD_GB", "PCC", "PCC", "PMC", "PMC",
           "PSEL", "PSEL"]
    if not join:                                                # mostly filter commands; join ones must be ignored
        ops += ["PWGB", "PCMP", "PCMP", "PCMP", "PCMP", "PCMP", "PRD", "PRD"]
    for _ in range(n):
        op = random.choice(ops)
        w = st["w"]
        if op == "PWGB":
            w = random.choice([8, 16, 32, 64])
            lo, hi = rand_bound(w), rand_bound(w)
            if random.random() < 0.3:
                lo, hi = min(lo, hi), max(lo, hi)
            mop = random.choice([0, 1, 2, 2, 1, 3])
            sgn, inv = random.getrandbits(1), int(random.random() < 0.3)
            gb = P.bound(lo, w) | (P.bound(hi, w) << 64) | ((({8: 0, 16: 1, 32: 2, 64: 3}[w]) | (sgn << 2) | (inv << 3)
                                                             | (mop << 4)) << 128)
            if random.random() < 0.1:                              # not repeated across 64 b: lanes see other bits
                gb = (gb & ~((1 << 128) - 1)) | random.getrandbits(128)
            gb |= random.getrandbits(122) << 134                    # ignored bits
            if random.random() < 0.1:                              # a set-word PWGB: bounds and config unchanged
                cmds.append(cmd("PWGB", gb=random.getrandbits(W), gbidx=random.randrange(1, 64),
                                x=random.getrandbits(W)))
                continue
            st.update(w=w, lo=lo, hi=hi)
            cmds.append(cmd("PWGB", gb=gb, x=random.getrandbits(W)))
        elif op == "PCMP":
            cmds.append(cmd("PCMP", x=lane_word(w, [st["lo"], st["hi"]]), addr=random.getrandbits(6)))
        elif op == "PLD_ROW":
            x = random.getrandbits(W)
            st["V"] = [x]
            cmds.append(cmd("PLD_ROW", x=x, addr=random.getrandbits(6)))
        elif op == "PLD_GB":
            g = random.getrandbits(W)
            st["V"] = [g]
            cmds.append(cmd("PLD_GB", gb=g, x=random.getrandbits(W)))
        elif op == "PCC":
            v = st["V"][0]
            x = 0
            for i in range(W // w):
                lane = (v >> (i * w)) & ((1 << w) - 1)
                x |= near(lane if random.random() < 0.8 else random.getrandbits(w), w) << (i * w)
            cmds.append(cmd("PCC", x=x, addr=random.getrandbits(6), cc=random.getrandbits(3)))
        elif op == "PSEL":
            cmds.append(cmd("PSEL", x=random.getrandbits(W), addr=random.getrandbits(6)))
        elif op == "PMC":
            cmds.append(cmd("PMC", dst=random.getrandbits(1), src=random.choice([0, 1, 2, 2, 3]),
                            inv=random.getrandbits(1), mop=random.choice([0, 1, 2, 3]), x=random.getrandbits(W)))
        elif op == "PRD":
            cmds.append(cmd("PRD", x=random.getrandbits(W)))
        else:
            cmds.append(cmd("NOP", x=random.getrandbits(W), gb=random.getrandbits(W)))
        if join and random.random() < 0.05:                         # make V and M1 observable through M
            cmds.append(cmd("PMC", dst=0, src=random.choice([1, 2]), mop=0))
            cmds.append(cmd("PRD"))
    return cmds


# ------------------------------------------------------------------ real-data replay
def replay(q, groups):
    tp = os.path.join(HERE, "..", "..", "tpch")
    sys.path.insert(0, tp)
    cwd = os.getcwd()
    os.chdir(tp)
    import numpy as np
    import bare as B
    import lookahead as L
    cache = {}

    def col(name):
        npz = L.COL[name][0] if name in L.COL else {"commit": "li_g2"}[name]
        if npz not in cache:
            cache[npz] = np.load(os.path.join(tp, "cache", f"{npz}_sf10.npz"))
        return cache[npz][name]

    if q == "q6":
        bms = {"q6": B.plan(6, 10)[0]}
    elif q in ("q12la", "q19la"):
        bms = L.plan(int(q[1:3]), 10)[0]
    elif q == "q12join":
        bms = None
    else:
        raise SystemExit(q)
    exp = {}                                                           # name -> per-record bits (functional model)
    if bms:
        for k, fs in bms.items():
            exp[k] = L.bitmap(fs, 10, {})
    else:
        exp["join"] = col("commit") < col("receipt")
    os.chdir(cwd)

    cmds, want = [], []
    init_m(cmds)
    for g in groups:
        for b in range(16):
            s, e = P.bank_records(g, b)
            if bms:
                for k, fs in bms.items():
                    for cname, lo, hi, op, inv in fs:
                        _, _, w0, nw, w = L.COL[cname]
                        lo = B.TMIN[w] if lo is None else lo
                        hi = B.TMAX[w] if hi is None else hi
                        mop = {"SET": 0, "AND": 1, "OR": 2}[op]
                        cmds.append(cmd("PWGB", gb=P.bounds_word(lo, hi, w, 1, inv, mop)))
                        for j, word in enumerate(P.words(P.column(col(cname), g, b), w)):
                            cmds.append(cmd("PCMP", x=word, addr=w0 + j))
                    cmds.append(cmd("PRD"))
                    bits = exp[k][s:e]
                    want.append(sum(int(v) << r for r, v in enumerate(bits)))
            else:                                                     # commit < receipt: PLD ROW + PCC
                cmds.append(cmd("PWGB", gb=P.bounds_word(0, 0, 16, 1, 0, 0)))
                cw = P.words(P.column(col("commit"), g, b), 16)
                rw = P.words(P.column(col("receipt"), g, b), 16)
                for j in range(16):
                    cmds.append(cmd("PLD_ROW", x=rw[j], addr=16 + j))
                    cmds.append(cmd("PCC", x=cw[j], addr=j, cc=0b100))
                cmds.append(cmd("PRD"))
                bits = exp["join"][s:e]
                want.append(sum(int(v) << r for r, v in enumerate(bits)))
    got = write(f"replay_{q}", cmds)
    bad = sum(a != b for a, b in zip(got, want))
    assert len(got) == len(want) and bad == 0, f"golden model differs from the functional model in {bad} PRDs"
    print(f"replay_{q}: golden model = functional model on all {len(want)} PRD words "
          f"({sum(bin(v).count('1') for v in want)} selected records)")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "random":
        name = sys.argv[2]
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 20000
        join = int(sys.argv[4]) if len(sys.argv) > 4 else 1
        setsel = int(sys.argv[5]) if len(sys.argv) > 5 else 1
        random.seed(int(sys.argv[6]) if len(sys.argv) > 6 else 1)
        write(name, random_cmds(n, join, setsel), join, setsel)
    else:
        random.seed(1)
        gs = [int(v) for v in (sys.argv[3] if len(sys.argv) > 3 else "0,1,777,14600").split(",")]
        replay(sys.argv[2], gs)
