#!/bin/sh
# Steam Deck (desktop mode) / Linux launcher. The game itself runs under Proton.
cd "$(dirname "$0")" || exit 1
if ! python3 -c "import tkinter" 2>/dev/null; then
  echo "Python 3 with Tkinter is required (python3 -c 'import tkinter' failed)."
  echo "See README.md, section 'Steam Deck'."
  printf "Press Enter to close. "
  read -r _
  exit 1
fi
exec python3 control_panel.py "$@"
