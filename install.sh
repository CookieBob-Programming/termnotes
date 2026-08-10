#!/usr/bin/env bash
set -euo pipefail

LIB=/usr/local/lib/termnotes
BIN=/usr/local/bin/termnotes
SERVICE=/etc/systemd/system/termnotes.service

if [[ $EUID -ne 0 ]]; then
  echo "Bitte mit sudo ausfuehren: sudo ./install.sh"
  exit 1
fi

command -v tmux >/dev/null 2>&1 || { echo "Fehler: tmux ist nicht installiert (sudo apt install tmux)." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Fehler: python3 ist nicht installiert." >&2; exit 1; }

TARGET_USER="${SUDO_USER:-$(id -un)}"
if [[ "$TARGET_USER" == "root" ]]; then
  TARGET_HOME=/root
else
  TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
fi

setup_autostart() {
  local user="$1" home="$2" shell_name="$3"
  local file
  case "$shell_name" in
    fish) file="$home/.config/fish/config.fish" ;;
    bash) file="$home/.bashrc" ;;
    zsh)  file="$home/.zshrc" ;;
    *)
      echo "Warnung: Autostart fuer Shell '$shell_name' wird nicht unterstuetzt."
      echo "  Manuell hinzufuegen: tmux has-session -t termnotes 2>/dev/null && termnotes"
      return 0
      ;;
  esac

  if [[ -f "$file" ]]; then
    sed -i "/^# >>> termnotes autostart >>>/,/^# <<< termnotes autostart <<</d" "$file"
  fi
  mkdir -p "$(dirname "$file")"

  case "$shell_name" in
    fish)
      cat >> "$file" <<'EOF'

# >>> termnotes autostart >>>
if status is-interactive; and not set -q TMUX
    tmux has-session -t termnotes 2>/dev/null; and termnotes
end
# <<< termnotes autostart <<<
EOF
      ;;
    bash|zsh)
      cat >> "$file" <<'EOF'

# >>> termnotes autostart >>>
if [[ $- == *i* ]] && [ -z "$TMUX" ]; then
    if tmux has-session -t termnotes 2>/dev/null; then
        termnotes
    fi
fi
# <<< termnotes autostart <<<
EOF
      ;;
  esac

  chown "$user" "$file" 2>/dev/null || true
  echo "  Autostart: $file (Shell erkannt: $shell_name)"
}

reload_config() {
  local user="$1" home="$2" shell_name="$3"
  case "$shell_name" in
    fish)
      runuser -u "$user" -- fish -c "source $home/.config/fish/config.fish" \
        && echo "  config.fish neu geladen (source)"
      ;;
    bash)
      runuser -u "$user" -- bash -c "source $home/.bashrc" \
        && echo "  .bashrc neu geladen (source)"
      ;;
    zsh)
      runuser -u "$user" -- zsh -c "source $home/.zshrc" \
        && echo "  .zshrc neu geladen (source)"
      ;;
  esac
}

mkdir -p "$LIB"
install -m 0644 termnotes.py "$LIB/termnotes.py"

cat > "$LIB/termnotes" <<EOF
#!/usr/bin/env bash
exec python3 "$LIB/termnotes.py" "\$@"
EOF
chmod +x "$LIB/termnotes"
ln -sf "$LIB/termnotes" "$BIN"

cat > "$SERVICE" <<EOF
[Unit]
Description=termnotes - Notizen-Daemon mit tmux-Panel
After=network.target

[Service]
Type=simple
User=$TARGET_USER
Environment=HOME=$TARGET_HOME
ExecStart=$BIN daemon run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable termnotes
systemctl restart termnotes
systemctl --no-pager status termnotes || true

LOGIN_SHELL="$(getent passwd "$TARGET_USER" | cut -d: -f7)"
if [[ -z "$LOGIN_SHELL" || "$LOGIN_SHELL" =~ (nologin|false)$ ]]; then
  echo "Warnung: Kein Login-Shell fuer $TARGET_USER gefunden, Autostart uebersprungen."
else
  echo "Erkannte Shell: $(basename "$LOGIN_SHELL")"
  setup_autostart "$TARGET_USER" "$TARGET_HOME" "$(basename "$LOGIN_SHELL")"
  reload_config "$TARGET_USER" "$TARGET_HOME" "$(basename "$LOGIN_SHELL")"
fi

echo
echo "Fertig installiert:"
echo "  Programm:  $BIN  (von ueberall ausfuehrbar)"
echo "  Service:   termnotes (systemd, laeuft als User $TARGET_USER)"
echo
echo "Verwendung:"
echo "  termnotes                 -> an Session anhaengen (Panel rechts)"
echo "  termnotes add name text   -> Note hinzufuegen"
echo "  termnotes rm name         -> Note loeschen"
echo "  termnotes setsize 40      -> Panel-Breite (Prozent)"
echo "  systemctl stop termnotes  -> Dienst stoppen"
echo "  sudo systemctl disable --now termnotes -> Dienst + Autostart deaktivieren"
