#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Aufruf: %s QUELLORDNER ZIELORDNER [h265-crf14|h265-crf18]\n' "$0" >&2
  exit 2
}

[[ $# -ge 2 && $# -le 3 ]] || usage
[[ -d "$1" ]] || { printf 'Fehler: Quellordner existiert nicht: %s\n' "$1" >&2; exit 1; }

src_root=$(cd "$1" && pwd -P)
mkdir -p "$2"
dst_root=$(cd "$2" && pwd -P)
profile=${3:-h265-crf18}
ffmpeg=${FFMPEG:-ffmpeg}
manifest="$dst_root/video-manifest.json"

case "$profile" in
  h265-crf14) crf=14 ;;
  h265-crf18) crf=18 ;;
  *) printf 'Fehler: unbekanntes Profil: %s\n' "$profile" >&2; usage ;;
esac

if ! command -v "$ffmpeg" >/dev/null 2>&1; then
  printf 'Fehler: ffmpeg nicht gefunden: %s\n' "$ffmpeg" >&2
  exit 1
fi
encoders=$("$ffmpeg" -hide_banner -encoders 2>/dev/null) || {
  printf 'Fehler: Encoderliste von ffmpeg konnte nicht gelesen werden.\n' >&2
  exit 1
}
if [[ "$encoders" != *libx265* ]]; then
  printf 'Fehler: ffmpeg besitzt keinen libx265-Encoder; H.265 ist erforderlich.\n' >&2
  exit 1
fi

count=0
tmp=''
cleanup() {
  if [[ -n "$tmp" && -f "$tmp" ]]; then
    rm -f "$tmp"
  fi
}
trap cleanup EXIT

while IFS= read -r -d '' src; do
  count=$((count + 1))
  rel=${src#"$src_root"/}
  dst="$dst_root/${rel%.*}.mp4"
  mkdir -p "$(dirname "$dst")"
  source_hash=$(shasum -a 256 "$src" | awk '{print $1}')
  source_bytes=$(wc -c < "$src" | tr -d '[:space:]')
  target_bytes=0
  [[ -f "$dst" ]] && target_bytes=$(wc -c < "$dst" | tr -d '[:space:]')

  if python3 - "$manifest" "$src" "$dst" "$source_hash" "$profile" "$target_bytes" <<'PY'
import json
import pathlib
import sys

manifest, source, target, source_hash, profile, target_bytes = sys.argv[1:]
path = pathlib.Path(manifest)
if not path.exists():
    raise SystemExit(1)
try:
    entries = json.loads(path.read_text(encoding="utf-8")).get("files", [])
except (OSError, json.JSONDecodeError) as error:
    print(f"Fehler: Manifest kann nicht gelesen werden: {error}", file=sys.stderr)
    raise SystemExit(2)
for entry in entries:
    if (entry.get("source") == source and entry.get("target") == target
            and entry.get("source_sha256") == source_hash
            and entry.get("profile") == profile
            and str(entry.get("target_size_bytes")) == target_bytes):
        raise SystemExit(0)
raise SystemExit(1)
PY
  then
    printf 'Unverändert, übersprungen: %s\n' "$rel"
    continue
  else
    result=$?
    if [[ $result -ne 1 ]]; then
      exit "$result"
    fi
  fi

  tmp="${dst%.mp4}.part.$$.${count}.mp4"
  printf 'Konvertiere (%s): %s\n' "$profile" "$rel"
  if ! "$ffmpeg" -hide_banner -y -i "$src" -map 0:v:0 -an \
    -c:v libx265 -crf "$crf" -pix_fmt yuv420p -tag:v hvc1 \
    -movflags +faststart "$tmp"; then
    printf 'Fehler: ffmpeg-Konvertierung fehlgeschlagen: %s\n' "$src" >&2
    exit 1
  fi
  mv -f "$tmp" "$dst"
  tmp=''
  target_bytes=$(wc -c < "$dst" | tr -d '[:space:]')

  # Manifest erst nach erfolgreicher Kodierung aktualisieren.
  if ! python3 - "$manifest" "$src" "$dst" "$source_hash" "$profile" "$source_bytes" "$target_bytes" <<'PY'
import json
import os
import pathlib
import sys

manifest, source, target, source_hash, profile, source_bytes, target_bytes = sys.argv[1:]
path = pathlib.Path(manifest)
try:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "files": []}
except (OSError, json.JSONDecodeError) as error:
    print(f"Fehler: Manifest kann nicht gelesen werden: {error}", file=sys.stderr)
    raise SystemExit(1)
data.setdefault("version", 1)
files = data.setdefault("files", [])
entry = {
    "source": source,
    "target": target,
    "source_sha256": source_hash,
    "profile": profile,
    "source_size_bytes": int(source_bytes),
    "target_size_bytes": int(target_bytes),
}
files[:] = [item for item in files if not (item.get("source") == source and item.get("target") == target)]
files.append(entry)
temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY
  then
    printf 'Fehler: Video wurde erstellt, aber das Manifest konnte nicht aktualisiert werden: %s\n' "$manifest" >&2
    exit 1
  fi
done < <(find "$src_root" -type f -name '*.webm' -print0)

if [[ $count -eq 0 ]]; then
  printf 'Fehler: Keine .webm-Dateien im Quellordner: %s\n' "$src_root" >&2
  exit 1
fi
