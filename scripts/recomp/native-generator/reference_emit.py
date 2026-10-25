#!/usr/bin/env python3
"""Development-only oracle: execute the frozen EH function emitter unchanged."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('nso', type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--base', required=True, type=lambda s: int(s, 0))
    parser.add_argument('--entry', required=True, type=lambda s: int(s, 0))
    parser.add_argument('--end', required=True, type=lambda s: int(s, 0))
    parser.add_argument('--label', action='append', default=[], type=lambda s: int(s, 0))
    parser.add_argument('--nle', action='append', default=[], type=lambda s: int(s, 0))
    parser.add_argument('--table', action='append', default=[])
    parser.add_argument('--hle')
    parser.add_argument('--simd', choices=('asm', 'c'), default='asm')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    script = args.reference / 'scripts/recomp/eh_gen.py'
    sys.path.insert(0, str(script.parent))
    spec = importlib.util.spec_from_file_location('frozen_eh_emitter', script)
    eh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eh)
    gen = eh.install(args.reference / 'scripts/recomp/upstream/generator')
    module = gen.Module('checkpoint', args.nso, args.base, args.simd)
    # Analysis is supplied explicitly to both emitters; no current Python algorithm is substituted.
    module.nle = sorted(set(args.nle))
    module._refs = set()
    tables = {}
    for item in args.table:
        pc, targets = item.split('=', 1)
        tables[int(pc, 0)] = 'all' if targets == 'all' else [int(t, 0) for t in targets.split(',')]
    code = '\n'.join(module.emit_function(args.entry, args.end, set(args.label) | {args.entry},
                                         tables, {args.entry: args.hle} if args.hle else {})) + '\n'
    if args.json:
        print(json.dumps({'code': code, 'refs': sorted(module._refs)}))
    else:
        print(code, end='')


if __name__ == '__main__':
    main()
