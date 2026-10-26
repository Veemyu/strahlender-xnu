#!/usr/bin/env python3
"""Development-only full scan oracle; execute frozen analysis without C emission."""
import argparse
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('nso')
    parser.add_argument('name')
    parser.add_argument('--base', required=True, type=lambda s: int(s, 0))
    parser.add_argument('--simd', choices=('asm', 'c'), default='asm')
    parser.add_argument('--entry-offsets')
    parser.add_argument('--setjmp-at', action='append', default=[], type=lambda s: int(s, 0))
    args = parser.parse_args()
    path = args.reference / 'scripts/recomp/eh_gen.py'
    spec = importlib.util.spec_from_file_location('frozen_full_analysis', path)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    tree = ast.parse(path.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'generate')
    cut = next(i for i, node in enumerate(fn.body) if isinstance(node, ast.Expr)
               and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
               and isinstance(node.value.func.value, ast.Name) and node.value.func.value.id == 'os'
               and node.value.func.attr == 'makedirs')
    result = ast.parse("""return {
      'rounds': rounds,
      'functions': [{'entry': a, 'end': end, 'labels': sorted(labels), 'tables': sorted(tables.items())}
                    for a, (end, labels, tables) in sorted(entries.items())],
      'jumptables': m.stats['jumptables'], 'br_all_labels': m.stats['br_all_labels'],
      'br_dispatch': m.stats['br_dispatch'], 'nle': m.nle}
""").body[0]
    fn.body = fn.body[:cut] + [result]
    fn.name = 'reference_full_analysis'
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(path), 'exec'), reference.__dict__)
    gen = reference.install(args.reference / 'scripts/recomp/upstream/generator')
    reference.EXTRA_SETJMP[:] = args.setjmp_at
    config = SimpleNamespace(nso=args.nso, name=args.name, base=args.base, simd=args.simd,
                             hle=None, entry_offsets=args.entry_offsets)
    print(json.dumps(reference.reference_full_analysis(gen, config)))


if __name__ == '__main__':
    main()
