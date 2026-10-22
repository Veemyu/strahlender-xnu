#!/bin/bash
# Runs locally on Linux: generator (c mode) + compile + link, with total time. Usage: build_all.sh [--force] [--gen-only] [--compile-only]
source "$(dirname "$0")/common.sh"
FORCE_ARG=""; DO_GEN=1; DO_CC=1
for a in "$@"; do case "$a" in --force) FORCE_ARG=--force;; --gen-only) DO_CC=0;; --compile-only) DO_GEN=0;; --tag=*) export TAG=${a#--tag=};; --jobs=*) export JOBS=${a#--jobs=};; --threshold=*) export THRESH_O0=${a#--threshold=};; *) die "Unknown argument '$a'.";; esac; done
t0=$(date +%s)
[ "$DO_GEN" = 1 ] && { bash "$(dirname "$0")/gen.sh" c || die "Generation failed."; }
t1=$(date +%s)
[ "$DO_CC" = 1 ] && { bash "$(dirname "$0")/compile.sh" c $FORCE_ARG || die "Compilation failed."; }
t2=$(date +%s)
echo "build_gesamt: gen $((t1 - t0)) s, compile+link $((t2 - t1)) s, together $((t2 - t0)) s" | tee logs/build-total.stats
