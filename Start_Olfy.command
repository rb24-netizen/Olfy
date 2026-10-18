#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
if bash start.sh --setup "$@"; then
  exit 0
else
  olfy_exit=$?
  echo ""
  echo "Olfy could not start. Read the message above and open Start_Here.html for help."
  if [[ -t 0 ]]; then read -r -p "Press Return to close this window. " olfy_reply; fi
  exit "$olfy_exit"
fi
