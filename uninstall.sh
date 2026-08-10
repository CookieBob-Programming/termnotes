#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Bitte mit sudo ausfuehren: sudo ./uninstall.sh"
  exit 1
fi

systemctl stop termnotes 2>/dev/null || true
systemctl disable termnotes 2>/dev/null || true
rm -f /etc/systemd/system/termnotes.service
rm -f /usr/local/bin/termnotes
rm -rf /usr/local/lib/termnotes
systemctl daemon-reload

echo "Deinstalliert. Deine Notizen unter ~/.termnotes bleiben erhalten."
