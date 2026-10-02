#!/usr/bin/env bash
# Installs what scan.sh needs: ClamAV, 7-Zip (with RAR), unar, YARA, pefile, plus the
# ClamAV signatures and YARA Forge rules. Safe to re-run: it only does what's missing or stale.
set -euo pipefail

ZIPSCAN_HOME="${ZIPSCAN_HOME:-$HOME/.cache/zipscan}"
mkdir -p "$ZIPSCAN_HOME"
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"
say() { echo "setup: $*" >&2; }

# --- system packages ---------------------------------------------------------------
apt_pkgs=()
command -v clamscan >/dev/null || apt_pkgs+=(clamav clamav-freshclam)
command -v 7z >/dev/null || apt_pkgs+=(7zip)
command -v unar >/dev/null || apt_pkgs+=(unar)
command -v file >/dev/null || apt_pkgs+=(file)
if ((${#apt_pkgs[@]})); then
  say "installing ${apt_pkgs[*]}"
  $SUDO apt-get install -y -q "${apt_pkgs[@]}" >/dev/null 2>&1 \
    || { $SUDO apt-get update -q >/dev/null 2>&1 && $SUDO apt-get install -y -q "${apt_pkgs[@]}" >/dev/null; }
fi
# RAR support for 7-Zip lives in a separate (non-free) package; unar covers RAR if it's unavailable.
if [ ! -e /usr/lib/7zip/Codecs/Rar.so ] && dpkg -s 7zip >/dev/null 2>&1; then
  $SUDO apt-get install -y -q 7zip-rar >/dev/null 2>&1 || say "7zip-rar unavailable; RAR files will use unar"
fi

# --- Python packages ---------------------------------------------------------------
if ! python3 -c "import yara, pefile" 2>/dev/null; then
  say "installing yara-python and pefile"
  python3 -m pip install -q yara-python pefile 2>/dev/null \
    || python3 -m pip install -q --break-system-packages yara-python pefile
fi

# --- ClamAV signatures (refreshed when older than 12 hours) ------------------------
if ! find /var/lib/clamav -maxdepth 1 -name 'daily.c[lv]d' -mmin -720 2>/dev/null | grep -q .; then
  say "downloading ClamAV signatures (~110 MB)"
  # freshclam runs as the clamav user, which may not be able to read a CA bundle in root's home
  # (common behind HTTPS-inspecting proxies). Hand it a readable copy.
  ca="${CURL_CA_BUNDLE:-${SSL_CERT_FILE:-}}"
  env_args=()
  if [ -n "$ca" ] && [ -f "$ca" ]; then
    $SUDO install -m 644 "$ca" /etc/ssl/zipscan-ca-bundle.crt
    env_args=(CURL_CA_BUNDLE=/etc/ssl/zipscan-ca-bundle.crt SSL_CERT_FILE=/etc/ssl/zipscan-ca-bundle.crt)
  fi
  $SUDO env ${env_args[@]+"${env_args[@]}"} freshclam --stdout >"$ZIPSCAN_HOME/freshclam.log" 2>&1 || true
  if ! ls /var/lib/clamav/main.c[lv]d /var/lib/clamav/daily.c[lv]d >/dev/null 2>&1; then
    say "ClamAV signatures failed to download; scans will say ClamAV couldn't run. Last log lines:"
    tail -5 "$ZIPSCAN_HOME/freshclam.log" >&2
  fi
fi

# --- YARA Forge community rules (refreshed weekly) ---------------------------------
rules="$ZIPSCAN_HOME/yara-forge.yar"
if [ ! -s "$rules" ] || [ -n "$(find "$rules" -mtime +7 2>/dev/null)" ]; then
  say "downloading YARA Forge rules"
  tmp="$(mktemp -d)"
  if curl -fsSL -o "$tmp/rules.zip" https://github.com/YARAHQ/yara-forge/releases/latest/download/yara-forge-rules-full.zip \
     && unzip -q -o "$tmp/rules.zip" -d "$tmp"; then
    mv "$tmp/packages/full/yara-rules-full.yar" "$rules"
    rm -f "$ZIPSCAN_HOME/yara-forge.compiled"
  else
    say "YARA rules failed to download; scans will say YARA couldn't run"
  fi
  rm -rf "$tmp"
fi
if [ -s "$rules" ] && [ ! -s "$ZIPSCAN_HOME/yara-forge.compiled" ]; then
  say "compiling YARA rules"
  python3 - "$rules" "$ZIPSCAN_HOME/yara-forge.compiled" <<'EOF'
import sys, yara
ext = dict(filename="", filepath="", extension="", filetype="", owner="")
yara.compile(filepath=sys.argv[1], externals=ext).save(sys.argv[2])
EOF
fi
