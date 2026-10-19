#!/usr/bin/env bash
# Spielstand zwischen Mac (Ryujinx-Ordner im Repo) und Ryujinx auf dem Ryzen abgleichen.
#   ryujinx_sync_save.sh status             Hashes beider Seiten
#   ryujinx_sync_save.sh push               Mac -> Ryzen (sichert den Ryzen-Stand vorher als tar)
#   ryujinx_sync_save.sh pull               Ryzen -> Mac-Arbeitskopie work/ryujinx-ryzen-save/ (überschreibt den Mac-Stand nie)
#   ryujinx_sync_save.sh restore <tar>      Ryzen-Stand aus einer Sicherung zurückspielen
# Zweck: Referenzbilder aus Ryujinx und unsere Builds (Unity, Rekompilation, iPad) sollen denselben Spielstand laden.
# Es werden nur SaveData.bin/Backup.bin in den Slots 0 und 1 der BD-Speicherstelle angefasst. Die Spiel-ID im Pfad
# (Ryujinx vergibt Nummern je Installation) wird über SaveData.bin der Größe 979108 Byte erkannt.
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
RZ_HOST="${RZ_HOST:-nobara}"
LOCAL_SAVE="${XNU_LOCAL_SAVE:-$HERE/Ryujinx/bis/user/save/0000000000000006/0}"   # Mac: nur lesen
RZ_SAVE_ROOT="${RZ_SAVE_ROOT:-.config/Ryujinx/bis/user/save}"                    # relativ zu ~ auf dem Ryzen
RZ_BACKUP_DIR="${RZ_BACKUP_DIR:-xnu-recomp/backup}"
SIZE=979108

rz() { ssh -o ConnectTimeout=10 -o BatchMode=yes "$RZ_HOST" "$@"; }
sha() { shasum -a 256 "$1" | cut -c1-16; }

rz_id() {
  rz "cd ~/$RZ_SAVE_ROOT && for d in */; do f=\$d/0/SaveData.bin; [ -f \$f ] && [ \$(stat -c %s \$f) -eq $SIZE ] && echo \${d%/}; done" | head -1
}

# Ryujinx muss das Spiel beenden, bevor der Stand getauscht wird (sonst überschreibt es ihn wieder).
check_not_running_game() {
  if rz "pgrep -f 'Ryujinx' >/dev/null && ls ~/.config/Ryujinx/Logs 2>/dev/null | tail -1 >/dev/null"; then
    echo "Hinweis: Ryujinx läuft auf dem Ryzen. Das Spiel dort vor dem Push beenden und danach neu starten."
  fi
}

case "${1:-status}" in
  status)
    id="$(rz_id)"; [ -n "$id" ] || { echo "Keine BD-Speicherstelle auf dem Ryzen gefunden." >&2; exit 1; }
    echo "Mac   : $(sha "$LOCAL_SAVE/SaveData.bin")  ($LOCAL_SAVE)"
    echo "Ryzen : slot0 $(rz "sha256sum ~/$RZ_SAVE_ROOT/$id/0/SaveData.bin | cut -c1-16")  slot1 $(rz "sha256sum ~/$RZ_SAVE_ROOT/$id/1/SaveData.bin | cut -c1-16")  (ID $id)"
    ;;
  push)
    [ -f "$LOCAL_SAVE/SaveData.bin" ] || { echo "Mac-Spielstand fehlt: $LOCAL_SAVE" >&2; exit 1; }
    id="$(rz_id)"; [ -n "$id" ] || { echo "Keine BD-Speicherstelle auf dem Ryzen gefunden." >&2; exit 1; }
    check_not_running_game
    ts="$(date +%Y%m%d-%H%M%S)"
    rz "mkdir -p ~/$RZ_BACKUP_DIR && tar -C ~/$RZ_SAVE_ROOT -cf ~/$RZ_BACKUP_DIR/ryujinx-save-$id-$ts.tar $id"
    echo "Sicherung auf dem Ryzen: ~/$RZ_BACKUP_DIR/ryujinx-save-$id-$ts.tar"
    for slot in 0 1; do
      for f in SaveData.bin Backup.bin; do
        [ -f "$LOCAL_SAVE/$f" ] || continue
        scp -q -o BatchMode=yes "$LOCAL_SAVE/$f" "$RZ_HOST:$RZ_SAVE_ROOT/$id/$slot/$f.xnu-tmp"
        rz "mv ~/$RZ_SAVE_ROOT/$id/$slot/$f.xnu-tmp ~/$RZ_SAVE_ROOT/$id/$slot/$f"
      done
    done
    echo "Mac $(sha "$LOCAL_SAVE/SaveData.bin") -> Ryzen $(rz "sha256sum ~/$RZ_SAVE_ROOT/$id/0/SaveData.bin | cut -c1-16") / $(rz "sha256sum ~/$RZ_SAVE_ROOT/$id/1/SaveData.bin | cut -c1-16")"
    ;;
  pull)
    id="$(rz_id)"; [ -n "$id" ] || { echo "Keine BD-Speicherstelle auf dem Ryzen gefunden." >&2; exit 1; }
    out="$HERE/work/ryujinx-ryzen-save"; mkdir -p "$out"
    scp -q -o BatchMode=yes "$RZ_HOST:$RZ_SAVE_ROOT/$id/0/SaveData.bin" "$out/SaveData.bin"
    echo "Ryzen-Stand nach $out/SaveData.bin ($(sha "$out/SaveData.bin"))"
    ;;
  restore)
    tarfile="${2:?Aufruf: restore <tar-Datei auf dem Ryzen, z. B. xnu-recomp/backup/ryujinx-save-4-....tar>}"
    rz "tar -C ~/$RZ_SAVE_ROOT -xf ~/$tarfile" && echo "Zurückgespielt: $tarfile"
    ;;
  *) echo "Aufruf: $0 status|push|pull|restore <tar>" >&2; exit 64 ;;
esac
