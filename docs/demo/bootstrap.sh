#!/usr/bin/env bash
# Installs the recording tools (vhs, ttyd, ffmpeg) into docs/demo/.tools/bin if missing. No sudo needed.
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"; B="$D/.tools/bin"; mkdir -p "$B"
[ -x "$B/vhs" ]  || GOBIN="$B" go install github.com/charmbracelet/vhs@latest
[ -x "$B/ttyd" ] || { curl -sL -o "$B/ttyd" https://github.com/tsl0922/ttyd/releases/latest/download/ttyd.x86_64; chmod +x "$B/ttyd"; }
if [ ! -x "$B/ffmpeg" ]; then
  python3 -m venv "$D/.tools/ffv"; "$D/.tools/ffv/bin/pip" -q install imageio-ffmpeg
  ln -sf "$("$D/.tools/ffv/bin/python" -c 'import imageio_ffmpeg as i;print(i.get_ffmpeg_exe())')" "$B/ffmpeg"
fi
echo "tools ready in $B"
# Chromium (used by vhs and Playwright) needs libasound.so.2; fetch it without root if the system lacks it.
if ! ldconfig -p | grep -q libasound.so.2 && [ ! -e "$D/.tools/lib/libasound.so.2" ]; then
  mkdir -p "$D/.tools/lib" "$D/.tools/dl" && (cd "$D/.tools/dl" && apt-get download libasound2t64 >/dev/null)
  dpkg-deb -x "$D"/.tools/dl/libasound2t64*.deb "$D/.tools/alsa"
  cp -a "$D"/.tools/alsa/usr/lib/x86_64-linux-gnu/libasound.so* "$D/.tools/lib/"
fi
