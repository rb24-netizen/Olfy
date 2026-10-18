#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  olfy_python=""
  for candidate in python3.12 python3.13 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,14)' 2>/dev/null; then
      olfy_python="$candidate"
      break
    fi
  done
  if [[ -z "$olfy_python" ]]; then
    echo "Olfy needs Python 3.11-3.13. Install Python 3.12 or 3.13 for macOS."
    echo "Official installers: https://www.python.org/downloads/macos/"
    echo "Reopen Terminal after installing, then run bash start.sh --setup."
    exit 1
  fi
  echo "Creating Olfy's local Python environment…"
  "$olfy_python" -m venv .venv
fi
if ! .venv/bin/python -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,14)' 2>/dev/null; then
  echo "The .venv Python environment cannot run or uses an unsupported version."
  echo "Keep your data folder. Rename .venv to .venv_old and run bash start.sh again."
  exit 1
fi
olfy_requirements="requirements.txt"
olfy_prepare=false
olfy_args=()
for argument in "$@"; do
  case "$argument" in
    --hardware) olfy_requirements="requirements-hardware.txt" ;;
    --serial) if [[ "$olfy_requirements" != "requirements-hardware.txt" ]]; then olfy_requirements="requirements-serial.txt"; fi ;;
    --prepare) olfy_prepare=true ;;
    *) olfy_args+=("$argument") ;;
  esac
done
olfy_signature=$(.venv/bin/python - "$olfy_requirements" <<'PY'
import hashlib, pathlib, sys
names = ["requirements.txt", sys.argv[1]]
payload = sys.version.encode() + b"".join(pathlib.Path(name).read_bytes() for name in names)
print(hashlib.sha256(payload).hexdigest())
PY
)
olfy_stamp=".venv/olfy-${olfy_requirements%.txt}.sha256"
if [[ ! -f "$olfy_stamp" ]] || [[ "$(cat "$olfy_stamp")" != "$olfy_signature" ]]; then
  echo "Installing Olfy's software dependencies. The first install needs internet access…"
  if ! .venv/bin/python -m pip install --disable-pip-version-check -r "$olfy_requirements"; then
    echo "Dependency installation did not finish. Check your internet connection and retry the same command."
    echo "Your recorded data has not been removed."
    exit 1
  fi
  .venv/bin/python -c 'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])' "$olfy_stamp" "$olfy_signature"
fi
if [[ "$olfy_prepare" == true ]]; then
  echo "Olfy software dependencies are installed. No sensor was connected and the app was not started."
  echo "Next: double-click Start_Olfy.command or run bash start.sh --setup."
  exit 0
fi
if [[ ${#olfy_args[@]} -gt 0 ]]; then
  exec .venv/bin/python -m olfy --reuse-running "${olfy_args[@]}"
else
  exec .venv/bin/python -m olfy --reuse-running
fi
