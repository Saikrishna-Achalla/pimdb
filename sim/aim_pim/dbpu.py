#!/usr/bin/env python3
"""AiM-style bank-level database processing unit (DB-PU): data layout, bit-exact functional model, ISR trace
generation, and the driver for the patched aim_simulator (Ramulator2).

Specification: isr_spec.json (same directory). Every operator below implements the semantics written there, on
NumPy arrays laid out exactly as the banks hold them: shape (rows, banks, T) = row r of bank b holds records
[(r*NB + b)*T, (r*NB + b + 1)*T) of the table (NB = 16 x channels).

Run with the owner's venv (has duckdb + numpy):  /home/sai/aimdb/.venv/bin/python -B <script>
"""
import math, os, re, subprocess, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.join(HERE, "..", "aim_simulator", "build", "ramulator2")
BASE_YAML = os.path.join(HERE, "..", "aim_simulator", "test", "example.yaml")
CACHE = os.path.join(HERE, "cache")
TRACES = os.path.join(CACHE, "traces")

TCK_NS = 0.5            # GDDR6_AiM_timing tCK_ps = 500
BANKS_PER_CH = 16
ROW_WORDS = 64          # 64 x 256-bit column words = 2 KB row per bank
WORD_B = 32
T_MAX = 512             # mask registers are 512 bits -> at most 512 records per row-tile
STAGE_WORDS = 8         # PU output staging buffer (words) before an internal write-back burst
PARTIALS_PER_SLOT = 4   # 32x32 partial products per MUL16 slot: 4 multipliers/bank x 1 ns slot (main assumption)
GAG_LANES_PER_SLOT = 4  # group aggregation: 8 groups x 4-input adder trees -> 4 values per GAG16 slot

# Timing parameters of the new commands (cycles of tCK = 0.5 ns). nREFI/nRFC: see isr_spec.json "refresh".
TIMING_MAIN = dict(nCCDCMP=2, nCCDALU=2, nCCDMUL=2, nCCDGAG=2, nPULAT=2, nPULATMUL=6, nPUWTR=11, nPUWR=33,
                   nREFI=3800, nRFC=240)
CMD_INTERVAL = {"CMP16": "nCCDCMP", "ALU16": "nCCDALU", "MUL16": "nCCDMUL", "GAG16": "nCCDGAG",
                "PUWR16": None, "MAC16": None}  # None -> nCCDL = 2


# ------------------------------------------------------------------------------------------------ simulator
def make_yaml(path, timing=None, refresh=True):
    t = open(BASE_YAML).read()
    timing = dict(TIMING_MAIN if timing is None else timing)
    if not refresh:
        timing.pop("nREFI", None); timing.pop("nRFC", None)
    lines = "".join(f"      {k}: {v}\n" for k, v in timing.items())
    t = t.replace("      preset: GDDR6_AiM_timing \n", "      preset: GDDR6_AiM_timing\n" + lines)
    if refresh:
        t = t.replace("      impl: AllBank\n", "      impl: AllBank\n      refresh_without_rank: true\n")
    assert "preset: GDDR6_AiM_timing\n" in t
    open(path, "w").write(t)
    return path


def simulate(trace_path, timing=None, refresh=True, yaml_path=None):
    """Run ramulator2; return dict(cycles, cmd={name: count summed over channels}, isr_cycles={...})."""
    os.makedirs(CACHE, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", dir=CACHE, delete=False) as f:
        yp = f.name
    try:
        make_yaml(yp, timing, refresh) if yaml_path is None else None
        out = subprocess.run([SIM, "-f", yaml_path or yp, "-t", trace_path], capture_output=True, text=True,
                             check=True).stdout
    finally:
        os.unlink(yp)
    cyc = int(re.search(r"memory_system_cycles:\s*(\d+)", out).group(1))
    cmd, isr = {}, {}
    for m in re.finditer(r"CH(\d+)_num_(\w+?)_commands:\s*(\d+)", out):
        cmd[m.group(2)] = cmd.get(m.group(2), 0) + int(m.group(3))
    for m in re.finditer(r"CH(\d+)_AiM_ISR_(\w+?)_cycles:\s*(\d+)", out):
        isr[m.group(2)] = isr.get(m.group(2), 0) + int(m.group(3))
    return dict(cycles=cyc, cmd=cmd, isr_cycles=isr)


def chmask(n_channels):
    return "0x%x" % ((1 << n_channels) - 1)


# ------------------------------------------------------------------------------------------------ layout
class Layout:
    """Row-tile (PAX-in-a-row) layout: each DRAM row of each bank holds T consecutive records of every listed
    column plus scratch slots for intermediates, mask slots and one header word (per-row counts).
    Tile i = r*NB + b  ->  row r, bank b (all banks of all used channels step through rows in lockstep)."""

    def __init__(self, n, cols, scratch=None, mask_slots=1, n_channels=1, T=None):
        self.n, self.cols, self.scratch = n, dict(cols), dict(scratch or {})
        self.widths = {**self.cols, **self.scratch}
        self.mask_slots, self.n_channels = mask_slots, n_channels
        self.nb = BANKS_PER_CH * n_channels
        if T is None:
            T = max(t for t in range(32, T_MAX + 1, 32) if self.used_words(t) <= ROW_WORDS)
        self.T = T
        assert self.used_words(T) <= ROW_WORDS, (T, self.used_words(T))
        self.tiles = math.ceil(n / T)
        self.rows = math.ceil(self.tiles / self.nb)
        assert self.rows <= 1 << 14, "does not fit the 16K rows of a bank"

    def used_words(self, T):
        return sum(T * w // WORD_B for w in self.widths.values()) + self.mask_slots * math.ceil(T / 256) + 1

    def W(self, name):           # 256-bit words of column `name` in one row-tile
        return self.T * self.widths[name] // WORD_B

    @property
    def mw(self):                # words per stored mask
        return math.ceil(self.T / 256)

    @property
    def base_util(self):         # fraction of the row holding base (input) columns
        return sum(self.T * w // WORD_B for w in self.cols.values()) / ROW_WORDS

    def arrange(self, a, pad=0):
        """1-D column (record order) -> (rows, NB, T) bank layout, padded."""
        out = np.full(self.rows * self.nb * self.T, pad, dtype=a.dtype)
        out[: len(a)] = a
        return out.reshape(self.rows, self.nb, self.T)

    def valid(self):
        idx = np.arange(self.rows * self.nb * self.T).reshape(self.rows, self.nb, self.T)
        return idx < self.n

    def record_ids(self):
        return np.arange(self.rows * self.nb * self.T, dtype=np.int64).reshape(self.rows, self.nb, self.T)


# ------------------------------------------------------------------------------------------------ PU state + functional semantics
DT = {1: np.int8, 2: np.int16, 4: np.int32, 8: np.int64}


class PU:
    """Functional state of all bank PUs (vectorized over banks). Bit-exact per isr_spec.json."""

    def __init__(self, L, data):
        self.L = L
        self.col = {k: L.arrange(np.asarray(v).astype(DT[L.widths[k]], copy=False)) for k, v in data.items()}
        self.mask = {}                                           # name -> bool (rows, NB, T)
        self.valid = L.valid()                                   # lane-valid (length register), costs nothing
        self.acc = np.zeros(L.nb, np.int64)                      # ACC (64-bit, wraps)
        self.gacc = {}                                           # aggregate name -> (NB, 8) int64
        self.cnt = np.zeros(L.nb, np.int64)                      # per-bank compaction count register
        self.compact = {}                                        # out name -> (packed (rows,NB,T), counts (rows,NB))

    def m(self, name):
        return self.valid if name is None else (self.mask[name] & self.valid)

    # --- compare: lo <= x <= hi (signed, column width), combine into mask register
    def cmp(self, col, lo, hi, dst, comb="SET", negate=False):
        x = self.col[col]
        r = (x >= lo) & (x <= hi)
        if negate:
            r = ~r
        if comb == "SET":
            self.mask[dst] = r
        elif comb == "AND":
            self.mask[dst] = self.mask[dst] & r
        elif comb == "OR":
            self.mask[dst] = self.mask[dst] | r
        else:
            raise ValueError(comb)

    # --- element-wise ALU with write-back (wrap to output width)
    def alu(self, kind, out, a, b=None, c=0, s=0):
        ow = DT[self.L.widths[out]]
        A = self.col[a].astype(np.int64)
        B = self.col[b].astype(np.int64) if b is not None else None
        if kind == "add":
            r = A + B
        elif kind == "sub":
            r = A - B
        elif kind == "add_c":
            r = A + c
        elif kind == "rsub_c":
            r = c - A
        elif kind == "add_shl":
            r = A + (B << s)
        elif kind == "widen":
            r = A
        else:
            raise ValueError(kind)
        self.col[out] = r.astype(ow)                              # astype wraps (two's complement)

    def mul(self, out, a, b):
        ow = DT[self.L.widths[out]]
        self.col[out] = (self.col[a].astype(np.int64) * self.col[b].astype(np.int64)).astype(ow)

    def sum(self, x, mask=None):
        self.acc += np.where(self.m(mask), self.col[x].astype(np.int64), 0).sum(axis=(0, 2))

    def mmac(self, a, b, mask=None):
        p = self.col[a].astype(np.int64) * self.col[b].astype(np.int64)
        self.acc += np.where(self.m(mask), p, 0).sum(axis=(0, 2))

    def gagg(self, name, key, val=None, mask=None):
        k = self.col[key].astype(np.int64)
        m = self.m(mask) & (k >= 0) & (k < 8)
        v = np.ones_like(k) if val is None else self.col[val].astype(np.int64)
        g = np.zeros((self.L.nb, 8), np.int64)
        for gi in range(8):
            g[:, gi] = np.where(m & (k == gi), v, 0).sum(axis=(0, 2))
        self.gacc[name] = self.gacc.get(name, np.zeros((self.L.nb, 8), np.int64)) + g

    def compaction(self, out, src, mask):
        """Bank-local compaction: per (row, bank) the selected lanes of `src` (or record ids if src is None) are
        packed to the front of the row's output slot; per-row count -> header word; per-bank count register."""
        m = self.m(mask)
        x = self.L.record_ids() if src is None else self.col[src]
        order = np.argsort(~m, axis=2, kind="stable")             # selected lanes first, original order kept
        packed = np.take_along_axis(np.where(m, x, 0), order, axis=2)
        counts = m.sum(axis=2)
        lane = np.arange(self.L.T)[None, None, :]
        packed = np.where(lane < counts[:, :, None], packed, 0)
        self.compact[out] = (packed, counts)
        self.cnt += counts.sum(axis=0)

    def mask_words(self, name):
        """Mask as it is stored in the row (bit j of the slot = lane j, little-endian), (rows, NB, mw*32) bytes."""
        b = np.packbits(self.m(name), axis=2, bitorder="little")
        pad = self.L.mw * 32 - b.shape[2]
        return np.pad(b, ((0, 0), (0, 0), (0, pad)))


def global_positions(counts_per_bank):
    """Host step after compaction: exclusive prefix sum over the per-bank count registers (bank-major order)."""
    return np.concatenate([[0], np.cumsum(counts_per_bank)[:-1]])


def gather_compacted(pu, out):
    """Host/GPU-side consumer of a bank-local compaction: concatenates segments in bank-major order using the
    per-bank prefix; returns the dense array. (Needs per-row counts from the header words.)"""
    packed, counts = pu.compact[out]
    segs = []
    for b in range(pu.L.nb):
        for r in range(pu.L.rows):
            segs.append(packed[r, b, : counts[r, b]])
    return np.concatenate(segs) if segs else np.zeros(0)


# ------------------------------------------------------------------------------------------------ operators: functional + trace
class Op:
    """A general operator. `fn(pu)` = functional semantics; `rowcmds(ctx, r)` = DRAM-side command classes for one
    row-tile under the schedule (ctx.sched in {'op', 'tile'})."""
    readout = 0       # RD_MAC lines (32 B per channel each) after the chain
    consts = 0        # WR_GB lines for constants
    host_readback = False

    def fn(self, pu):
        raise NotImplementedError

    def rowcmds(self, ctx, r):
        raise NotImplementedError


def _chunked(reads_cls, reads, writes):
    """Read/write interleaving through the 8-word output staging buffer."""
    if writes == 0:
        return [(reads_cls, reads)]
    k = math.ceil(writes / STAGE_WORDS)
    out, rd_done, wr_done = [], 0, 0
    for i in range(k):
        rd = round(reads * (i + 1) / k) - rd_done
        wr = min(STAGE_WORDS, writes - wr_done)
        out += [(reads_cls, rd), ("PWB", wr)]
        rd_done += rd; wr_done += wr
    return out


def _mask_load(ctx, mask):
    # op-at-a-time: a mask produced by an earlier operator lives in the row's mask slot -> load it (1 read/word)
    return [("PALU", ctx.L.mw)] if (mask is not None and ctx.sched == "op") else []


class CMP(Op):
    consts = 1

    def __init__(self, col, lo, hi, dst="M0", comb="SET", store=False, negate=False):
        self.col, self.lo, self.hi, self.dst, self.comb, self.store, self.negate = col, lo, hi, dst, comb, store, negate
        self.name = f"CMP({col})"

    def fn(self, pu):
        pu.cmp(self.col, self.lo, self.hi, self.dst, self.comb, self.negate)

    def rowcmds(self, ctx, r):
        L, c = ctx.L, []
        if ctx.sched == "op" and self.comb != "SET":
            c.append(("PALU", L.mw))                       # load the stored mask to combine into
        c.append(("PCMP", L.W(self.col)))
        if ctx.sched == "op" or self.store:
            c.append(("PWB", L.mw))                        # store the mask to the row's mask slot
        return c


class EW(Op):
    def __init__(self, kind, out, a, b=None, c=0, s=0):
        self.kind, self.out, self.a, self.b, self.c, self.s = kind, out, a, b, c, s
        self.consts = 1 if b is None and kind != "widen" else 0
        self.name = f"EW_{kind}({a}{','+b if b else ''})"

    def fn(self, pu):
        pu.alu(self.kind, self.out, self.a, self.b, self.c, self.s)

    def rowcmds(self, ctx, r):
        L = ctx.L
        reads = L.W(self.a) + (L.W(self.b) if self.b else 0)
        return _chunked("PALU", reads, L.W(self.out))


def mul_slots(L, a, b):
    pa, pb = math.ceil(L.widths[a] / 4), math.ceil(L.widths[b] / 4)
    partials = 3 if (pa == 2 and pb == 2) else pa * pb       # 64x64 truncated to 64 bits: lo*lo, lo*hi, hi*lo
    return max(L.W(a) + L.W(b), math.ceil(L.T * partials / PARTIALS_PER_SLOT))


class MUL(Op):
    def __init__(self, out, a, b):
        self.out, self.a, self.b = out, a, b
        self.name = f"MUL({a},{b})"

    def fn(self, pu):
        pu.mul(self.out, self.a, self.b)

    def rowcmds(self, ctx, r):
        return _chunked("PMUL", mul_slots(ctx.L, self.a, self.b), ctx.L.W(self.out))


class SUM(Op):
    readout = 4                                             # 16 banks x 8 B / 32 B per RD_MAC
    host_readback = True

    def __init__(self, x, mask=None):
        self.x, self.mask = x, mask
        self.name = f"SUM({x})"

    def fn(self, pu):
        pu.sum(self.x, self.mask)

    def rowcmds(self, ctx, r):
        return _mask_load(ctx, self.mask) + [("PALU", ctx.L.W(self.x))]


class MMAC(Op):
    readout = 4
    host_readback = True

    def __init__(self, a, b, mask=None):
        self.a, self.b, self.mask = a, b, mask
        self.name = f"MMAC({a},{b})"

    def fn(self, pu):
        pu.mmac(self.a, self.b, self.mask)

    def rowcmds(self, ctx, r):
        return _mask_load(ctx, self.mask) + [("PMUL", mul_slots(ctx.L, self.a, self.b))]


class GAGG(Op):
    """Small-group aggregation: for every value column, 8 group accumulators indexed by a key (0..7); plus count."""
    host_readback = True

    def __init__(self, key, vals, mask=None, count=True):
        self.key, self.vals, self.mask, self.count = key, list(vals), mask, count
        self.readout = 32 * (len(self.vals) + (1 if count else 0))   # 16 banks x 8 groups x 8 B / 32 B
        self.name = f"GAGG({key};{','.join(self.vals)}{';count' if count else ''})"

    def fn(self, pu):
        for v in self.vals:
            pu.gagg(v, self.key, v, self.mask)
        if self.count:
            pu.gagg("count", self.key, None, self.mask)

    def rowcmds(self, ctx, r):
        L = ctx.L
        c = _mask_load(ctx, self.mask)
        for v in self.vals:
            c.append(("PGAG", L.W(self.key) + max(L.W(v), L.T // GAG_LANES_PER_SLOT)))
        if self.count:
            c.append(("PGAG", L.W(self.key)))
        return c


class COMPACT(Op):
    readout = 2                                             # per-bank 32-bit count registers: 16 x 4 B / 32 B
    host_readback = True

    def __init__(self, out, src, mask, width):
        self.out, self.src, self.mask, self.width = out, src, mask, width
        self.name = f"COMPACT({src or 'rowid'})"

    def fn(self, pu):
        pu.compaction(self.out, self.src, self.mask)

    def rowcmds(self, ctx, r):
        L = ctx.L
        src_words = L.T * self.width // WORD_B
        reads = L.W(self.src) if self.src else 0          # row ids are generated from (row, bank, lane): no read
        if ctx.issuer == "host":
            wr = src_words                                  # host-paced: count unknown -> write the whole slot
        else:
            cnt = ctx.pu.compact[self.out][1][r, : BANKS_PER_CH]   # sequencer: max count over the channel's banks
            wr = math.ceil(int(cnt.max()) * self.width / WORD_B)
        c = _mask_load(ctx, self.mask)
        if reads:
            c += _chunked("PALU", reads, wr)
        else:
            c += [("PALU", 1)] if wr == 0 else _chunked("PALU", 1, wr)  # one slot to run the packer even if empty
        c.append(("PWB", 1))                                # per-row count -> header word
        return c


class Ctx:
    def __init__(self, L, sched, pu, issuer):
        self.L, self.sched, self.pu, self.issuer = L, sched, pu, issuer


# ------------------------------------------------------------------------------------------------ chain -> functional result + trace
def run_functional(L, data, ops):
    pu = PU(L, data)
    for op in ops:
        op.fn(pu)
    return pu


def write_trace(path, L, pu, ops, sched, readouts=True, mask_readout=None, compact_readout=None, issuer=None):
    """Emit the ISR trace. sched='op': operator-at-a-time (each operator sweeps all rows; masks/intermediates
    persist in the rows between operators). sched='tile': tile-at-a-time (the whole chain runs on one open row,
    masks stay in PU registers). Returns counts for the pacing model."""
    ctx = Ctx(L, sched, pu, issuer or ("host" if sched == "op" else "seq"))
    ch = chmask(L.n_channels)
    lines = ["W GPR 0", "W GPR 1"]
    n_consts = sum(op.consts for op in ops)
    for _ in range(n_consts):
        lines.append(f"AiM WR_GB 1 0 {ch}")
    lines.append(f"AiM WR_BIAS 1 {ch}")                      # clear accumulators / count registers
    steps = 0

    def emit_row(op, r):
        nonlocal steps
        steps += 1
        for cls, n in op.rowcmds(ctx, r):
            if n > 0:
                lines.append(f"AiM {cls}_ABK {n} {ch} {r}")

    if sched == "op":
        for op in ops:
            for r in range(L.rows):
                emit_row(op, r)
    else:
        for r in range(L.rows):
            for op in ops:
                emit_row(op, r)
    n_compute_lines = len(lines)
    ro = 0
    if readouts:
        for op in ops:
            for _ in range(op.readout):
                lines.append(f"AiM RD_MAC 0 {ch}")
                ro += 1
        if mask_readout is not None:      # GPU reads the stored bitmask words (conventional reads, all banks)
            for r in range(L.rows):
                for b in range(BANKS_PER_CH):
                    for _ in range(L.mw):          # RD_SBK = one 32 B column read of one bank
                        lines.append(f"AiM RD_SBK 0 {ch} {b} {r}")
                        ro += 1
        if compact_readout is not None:   # GPU reads the packed segments (header word + used words)
            packed, counts = pu.compact[compact_readout[0]]
            w = compact_readout[1]
            for r in range(L.rows):
                for b in range(BANKS_PER_CH):
                    for _ in range(1 + math.ceil(int(counts[r, b]) * w / WORD_B)):
                        lines.append(f"AiM RD_SBK 0 {ch} {b} {r}")
                        ro += 1
    lines.append("AiM EOC")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    isr = sum(1 for l in lines if l.startswith("AiM") and not l.endswith("EOC"))
    return dict(isr_lines=isr, op_steps=steps, readout_isrs=ro, consts=n_consts, n_ops=len(ops),
                compute_isr_lines=n_compute_lines - 2)


def strip_readout(src, dst):
    keep = [l for l in open(src) if not (l.startswith("AiM RD_MAC") or l.startswith("AiM RD_SBK"))]
    open(dst, "w").writelines(keep)


def column_cycles(cmd, timing):
    """Cycles the bank column path is busy with PU column commands (compute + internal write-back)."""
    c = 0
    for k, p in CMD_INTERVAL.items():
        c += cmd.get(k, 0) * (timing.get(p, 2) if p else 2)
    return c


def measure(trace, timing=None, n_channels=1, breakdown=True):
    """Simulate with refresh, without refresh, and without read-out -> breakdown (cycles)."""
    timing = dict(TIMING_MAIN if timing is None else timing)
    full = simulate(trace, timing, refresh=True)
    res = dict(cycles=full["cycles"], cmd=full["cmd"])
    if breakdown:
        noref = simulate(trace, timing, refresh=False)
        t2 = trace + ".noreadout"
        strip_readout(trace, t2)
        nor = simulate(t2, timing, refresh=False)
        os.unlink(t2)
        comp = column_cycles(nor["cmd"], timing) / n_channels
        res.update(refresh_cyc=full["cycles"] - noref["cycles"], readout_cyc=noref["cycles"] - nor["cycles"],
                   compute_cyc=comp, rowov_cyc=nor["cycles"] - comp)
    return res
