#!/bin/bash
# Baut aus tools/opendpr, dem AssetRipper-Export und dem RomFS ein Unity-Projekt.
# Eigenes Skript, enthaelt keinen opendpr-Code. Bricht ab, wenn das Ziel schon existiert.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/tools/opendpr"
FIX="$ROOT/tools/Lumi_Small_Scripts/asset_ripper_resources/fix_pathids.py"
EXPORT="$ROOT/work/ripper/out/ExportedProject/Assets"
STREAMING="$ROOT/work/romfs/Data/StreamingAssets"
DEST="$ROOT/work/opendpr-project"
STAGE="$ROOT/work/opendpr-stage"
MIN_FREE_KB=$((15 * 1024 * 1024))

free_kb() { df -k /System/Volumes/Data | awk 'NR==2 {print $4}'; }
log() { echo "[$(date +%H:%M:%S)] $* | frei: $(df -h /System/Volumes/Data | awk 'NR==2 {print $4}')"; }

[ -d "$SRC" ] && [ -f "$FIX" ] && [ -d "$EXPORT" ] && [ -d "$STREAMING" ] || { echo "Eingabe fehlt"; exit 1; }
[ ! -e "$DEST" ] && [ ! -e "$STAGE" ] || { echo "Ziel oder Stage existiert schon: $DEST / $STAGE"; exit 1; }
[ "$(free_kb)" -ge "$MIN_FREE_KB" ] || { echo "Weniger als 15 GB frei"; exit 1; }
log "Start"

# 1. Repo ohne .git kopieren
cp -c -R "$SRC" "$DEST"
rm -rf "$DEST/.git"
log "1: opendpr kopiert"

# 2. Export (ohne StreamingAssets) als input/ bereitstellen und Skript laufen lassen
mkdir -p "$STAGE/input"
for d in "$EXPORT"/*/; do
  n="$(basename "$d")"
  [ "$n" = "StreamingAssets" ] && continue
  cp -c -R "$d" "$STAGE/input/$n"
done
find "$STAGE/input" -name .DS_Store -delete
(cd "$STAGE" && python3 "$FIX") > "$STAGE/fix_pathids.log" 2>&1
log "2: fix_pathids fertig ($(wc -l < "$STAGE/fix_pathids.log") Logzeilen)"

OUT="$STAGE/output"
A="$DEST/Assets"

# 3. Handschritte
for f in AkWwiseInitializationSettings Mac Switch Windows; do
  rm -f "$OUT/MonoBehaviour/$f.asset" "$OUT/MonoBehaviour/$f.asset.meta"
done
TMP="$A/TextMesh Pro/Resources"
mkdir -p "$TMP"
for n in "fonts & materials" "sprite assets" "style sheets" \
         "LineBreaking Following Characters.txt" "LineBreaking Leading Characters.txt"; do
  mv "$OUT/Resources/$n" "$TMP/$n"
  [ -f "$OUT/Resources/$n.meta" ] && mv "$OUT/Resources/$n.meta" "$TMP/$n.meta"
done
mv "$OUT/Scenes/level0.unity" "$OUT/Scenes/level0.unity.meta" "$A/"
mkdir -p "$A/Resources"
for e in "$OUT"/*; do
  n="$(basename "$e")"
  if [ "$n" = "Resources" ]; then
    cp -c -R "$e"/. "$A/Resources/"
  elif [ "$n" = "Scenes" ]; then
    :
  else
    mv "$e" "$A/Resources/$n"
  fi
done
sed -i '' 's/AssetAssistant, Version=0\.0\.0\.0,/Assembly-CSharp, Version=1.6.28.12450,/g' "$A/Resources/StartupSettings.asset"
log "3: Handschritte fertig"

# 4. Leerer Ordner fuer die (fehlenden) Windows-Bundles
mkdir -p "$DEST/AssetBundles/Editor"

# 5. StreamingAssets (APFS-Clone, mit vorhandenem AK-Ordner zusammengefuehrt), Switch -> Windows
mkdir -p "$A/StreamingAssets"
cp -c -R "$STREAMING"/. "$A/StreamingAssets/"
mv "$A/StreamingAssets/Audio/GeneratedSoundBanks/Switch" "$A/StreamingAssets/Audio/GeneratedSoundBanks/Windows"
log "5: StreamingAssets fertig"
echo "Stage (kann geloescht werden): $STAGE"
