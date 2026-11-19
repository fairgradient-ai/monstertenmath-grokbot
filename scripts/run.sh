#!/usr/bin/env bash
# run.sh <command> [arguments]: the only way the Grok Bot touches Instagram.
# It runs the engine from this checkout with the desk's config and state. In rehearsal mode nothing is posted.
#   sweep | inbox | draft N | send N... | discard N... | hide N... | status | stats | doctor [--full]
#   phase [show|building|open] | go-live | rehearse | token status|refresh | version
# Commands that post or change the mode or phase need --owner-tapped, which the Grok Bot passes only after
# the owner approves the "Ask first" card (routines/autoreview.txt). Exit: 0 done, 1 refused, 2 config, 3 infra.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=env.sh
. "$HERE/env.sh"

COMMANDS="sweep inbox reply draft send discard hide status stats doctor phase go-live rehearse token examples scout creators outreach brief version"
cmd=${1:-}
case " $COMMANDS " in
  *" $cmd "*) [ -n "$cmd" ] || { echo "FAILED: no command. Commands: $COMMANDS"; exit 2; } ;;
  *) echo "FAILED: unknown command '$cmd'. Commands: $COMMANDS"; exit 2 ;;
esac

if [ -z "$MT_PYTHON" ] || ! "$MT_PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  echo "FAILED: no Python 3.11 or newer. Run: bash $MT_CHECKOUT/scripts/install.sh"
  exit 3
fi
export PYTHONPATH="$MT_CHECKOUT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$MT_PYTHON" -m monsterbot "$@"
