"""Bounded, spawn-based workers for the owned EH generator extension.

Upstream LASRecomp remains unchanged. Workers own their lifter/Unicorn state;
no emulator or Python instruction cache is shared between processes.
"""
from collections import deque
from concurrent.futures import ProcessPoolExecutor
import multiprocessing


_MODULE = None
_HLE = None
_EH = None


class SerialScan(Exception):
    """Unicorn jump-table discovery retains state and must follow address order."""


def serial_jump_table(*args):
    raise SerialScan


def initialize(las_dir, name, nso, base, simd, setjmp, hle):
    global _MODULE, _HLE, _EH
    import eh_gen
    _EH = eh_gen
    eh_gen.EXTRA_SETJMP[:] = setjmp
    gen = eh_gen.install(las_dir)
    _MODULE = gen.Module(name, nso, base, simd)
    _HLE = hle


def run_batch(task):
    kind, items = task
    m = _MODULE
    m.cache.clear()
    m.wide_tables.clear()
    m.stats.clear()
    _EH.STATS.clear()
    if kind == "scan":
        result = []
        stats, eh_stats = {}, {}
        original = m.jump_table
        m.jump_table = serial_jump_table
        try:
            for a, end in items:
                m.stats.clear()
                _EH.STATS.clear()
                try:
                    value = m.scan(a, end)
                except SerialScan:
                    value = None
                result.append((a, end, value))
                if value is not None:
                    for k, v in m.stats.items():
                        stats[k] = stats.get(k, 0) + v
                    for k, v in _EH.STATS.items():
                        eh_stats[k] = eh_stats.get(k, 0) + v
        finally:
            m.jump_table = original
    else:
        result = []
        for a, end, labels, tables in items:
            m._refs = set()
            lines = m.emit_function(a, end, labels, tables, _HLE)
            result.append((a, lines, m._refs))
        stats, eh_stats = dict(m.stats), dict(_EH.STATS)
    # Keep at most one batch's decoded instructions alive per worker.
    m.cache.clear()
    return result, stats, eh_stats


def batches(items, byte_budget=0x20000):
    """Contiguous guest ranges amortize IPC while bounding decoded-code memory."""
    batch, size = [], 0
    for item in items:
        batch.append(item)
        size += item[1] - item[0]
        if size >= byte_budget or len(batch) >= 256:
            yield batch
            batch, size = [], 0
    if batch:
        yield batch


class Workers:
    def __init__(self, jobs, las_dir, args, hle):
        self.jobs = jobs
        self.pool = ProcessPoolExecutor(
            max_workers=jobs, mp_context=multiprocessing.get_context("spawn"),
            initializer=initialize,
            initargs=(str(las_dir), args.name, args.nso, args.base, args.simd,
                      args.setjmp_at, hle))

    def map(self, kind, items):
        """Ordered results with only two batches per worker queued (Python >=3.9)."""
        source = iter(batches(items))
        pending = deque()
        for _ in range(self.jobs * 2):
            batch = next(source, None)
            if batch is None:
                break
            pending.append(self.pool.submit(run_batch, (kind, batch)))
        while pending:
            yield pending.popleft().result()
            batch = next(source, None)
            if batch is not None:
                pending.append(self.pool.submit(run_batch, (kind, batch)))

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
