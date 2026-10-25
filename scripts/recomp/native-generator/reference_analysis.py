#!/usr/bin/env python3
"""Development oracle: execute only the frozen generator's initial analysis.

The AST cut stops immediately before the iterative function scan. The original
prefix is executed verbatim rather than duplicating its boundary/ADR algorithms.
Never packaged or called by the native executable.
"""
import argparse
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True, type=Path)
    ap.add_argument("nso")
    ap.add_argument("name")
    ap.add_argument("--base", required=True, type=lambda s: int(s, 0))
    ap.add_argument("--entry-offsets")
    ap.add_argument("--setjmp-at", action="append", default=[], type=lambda s: int(s, 0))
    args = ap.parse_args()
    path = args.reference / "scripts/recomp/eh_gen.py"
    spec = importlib.util.spec_from_file_location("frozen_eh_generator", path)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    tree = ast.parse(path.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "generate")
    cut = next(i for i, node in enumerate(function.body) if isinstance(node, ast.Assign)
               and any(isinstance(name, ast.Name) and name.id == "scanned" for name in ast.walk(node.targets[0])))
    result = ast.parse("return {'boundaries': starts, 'initial_entries': sorted(start_set), "
                       "'landing_pads': sorted(m.lp_set), 'setjmp_returns': sorted(m.setjmp_set), "
                       "'adr_bases_kept_inside': STATS['adr_jumptable_base_kept_inside']}").body[0]
    function.body = function.body[:cut] + [result]
    function.name = "reference_initial_analysis"
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, str(path), "exec"), reference.__dict__)
    gen = reference.install(args.reference / "scripts/recomp/upstream/generator")
    reference.EXTRA_SETJMP[:] = args.setjmp_at
    config = SimpleNamespace(nso=args.nso, name=args.name, base=args.base, simd="asm", hle=None,
                             entry_offsets=args.entry_offsets)
    print(json.dumps(reference.reference_initial_analysis(gen, config)))


if __name__ == "__main__":
    main()
