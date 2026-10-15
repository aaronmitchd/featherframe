#!/usr/bin/env bash
#
# Set up a Pimoroni Inky Impression wired to this Pi to show Featherframe.
# Safe to re-run. Run it after ./install.sh, from server/:
#
#     ./scripts/install_inky.sh [--orientation portrait|landscape] [--turn 90|270]
#
# It turns on I2C and SPI and frees the chip-select pin the panel needs (as
# Pimoroni's own installer does), adds this user to the spi, i2c and gpio
# groups, installs Pimoroni's library into the server's venv, and installs the
# featherframe-inky service. A reboot is needed the first time.
set -euo pipefail

SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$SERVER_DIR/.venv"
UNIT=/etc/systemd/system/featherframe-inky.service
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --orientation|--turn) ARGS+=("$1" "$2"); shift ;;
    --flip) ARGS+=("$1") ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
  shift
done
REBOOT=0

[ -x "$VENV/bin/python" ] || { echo "Run ./install.sh first (no venv at $VENV)."; exit 1; }

echo "==> Turning on I2C and SPI…"
if command -v raspi-config >/dev/null 2>&1; then
  sudo raspi-config nonint do_i2c 0 || echo "    could not turn on I2C"
  sudo raspi-config nonint do_spi 0 || echo "    could not turn on SPI"
fi
BOOT=/boot/firmware/config.txt
[ -f "$BOOT" ] || BOOT=/boot/config.txt
for line in dtoverlay=i2c1 dtoverlay=i2c1-pi5 dtoverlay=spi0-0cs; do
  grep -qxF "$line" "$BOOT" && continue
  echo "$line" | sudo tee -a "$BOOT" >/dev/null
  echo "    added $line to $BOOT"
  REBOOT=1
done

for g in spi i2c gpio; do
  getent group "$g" >/dev/null 2>&1 || continue
  id -nG "$USER" | grep -qw "$g" && continue
  sudo usermod -aG "$g" "$USER"
  echo "    added $USER to the $g group"
  REBOOT=1
done

echo "==> Installing Pimoroni's inky library…"
sudo apt-get install -y python3-dev >/dev/null 2>&1 || true   # spidev builds from source
"$VENV/bin/pip" install -r "$SERVER_DIR/requirements-inky.txt"

echo "==> Installing the featherframe-inky service…"
sudo tee "$UNIT" >/dev/null <<UNIT
[Unit]
Description=Featherframe on the Inky Impression
After=featherframe.service network-online.target
Wants=featherframe.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$SERVER_DIR
ExecStart=$VENV/bin/python $SERVER_DIR/scripts/inky_frame.py ${ARGS[@]+"${ARGS[@]}"}
Restart=on-failure
RestartSec=30
Nice=10

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable featherframe-inky.service >/dev/null 2>&1

if [ "$REBOOT" -eq 1 ]; then
  echo "==> Done. Reboot to turn on the panel's pins: sudo reboot"
  echo "    The Inky starts on its own after the reboot."
else
  sudo systemctl restart featherframe-inky.service
  echo "==> Done. The Inky is starting: journalctl -u featherframe-inky -f"
fi
echo "    It shows a short id first. Add it in the Featherframe webapp's Frames list."
