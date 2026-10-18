#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
bash start.sh --doctor "$@"
olfy_exit=$?
if [[ -t 0 ]]; then read -r -p "Press Return to close this window. " olfy_reply; fi
exit "$olfy_exit"
