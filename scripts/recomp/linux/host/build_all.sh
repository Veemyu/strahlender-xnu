#!/bin/bash
# Runs on the Linux host: generator (c mode) + compile + link, with total time. Usage: build_all.sh [--neu] [--nur-gen] [--nur-compile]
source "$(dirname "$0")/common.sh"
NEU=""; DO_GEN=1; DO_CC=1
for a in "$@"; do case "$a" in --neu) NEU=--neu;; --nur-gen) DO_CC=0;; --nur-compile) DO_GEN=0;; --tag=*) export TAG=${a#--tag=};; --jobs=*) export JOBS=${a#--jobs=};; --schwelle=*) export THRESH_O0=${a#--schwelle=};; *) die "Unknown argument '$a'.";; esac; done
t0=$(date +%s)
[ "$DO_GEN" = 1 ] && { bash "$(dirname "$0")/gen.sh" c || die "Generation failed."; }
t1=$(date +%s)
[ "$DO_CC" = 1 ] && { bash "$(dirname "$0")/compile.sh" c $NEU || die "Compilation failed."; }
t2=$(date +%s)
echo "build_gesamt: gen $((t1 - t0)) s, compile+link $((t2 - t1)) s, together $((t2 - t0)) s" | tee logs/build-total.stats
