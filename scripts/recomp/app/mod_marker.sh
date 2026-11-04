# Sourced by make_app.sh. mod-build.txt in a mod app's Resources: mod name, mods folder, mod folder, kind
# (exefs: code compiled into the app; romfs: files only), one per line. Read by choose_mod in runtime/app/app_config.c.
write_mod_marker() {
  local file="$1" name="$2" library="$3" root="$4" kind="$5"
  case "$name$library$root" in *$'\n'*|*$'\r'*) echo "ERROR: newline in mod name or path" >&2; return 2 ;; esac
  case "$kind" in exefs|romfs) ;; *) echo "ERROR: --mod-kind must be exefs or romfs" >&2; return 2 ;; esac
  printf '%s\n%s\n%s\n%s\n' "$name" "$library" "$root" "$kind" > "$file"
}
