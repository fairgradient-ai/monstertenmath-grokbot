#!/usr/bin/env bash
# install.sh: set up the desk (/workspace/monsterten-desk). Safe to run again: it never overwrites the
# config, the state or the token. The engine needs only Python 3.11+ (no packages); if the computer has
# none, it fetches uv and a managed Python into the desk. Prints ok:, skip: or FAIL: per step.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=env.sh
. "$HERE/env.sh"

mkdir -p "$MT_DESK/state" "$MT_DESK/logs" "$MT_OPT"
chmod 700 "$MT_DESK"

py_ok() { [ -n "$1" ] && "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; }

# 1. Python 3.11+
if py_ok "$MT_DESK/venv/bin/python"; then
  echo "ok: $("$MT_DESK/venv/bin/python" -V 2>&1) (desk)"
elif py_ok "$(command -v python3 || true)"; then
  echo "ok: $(python3 -V 2>&1) (system)"
else
  if [ ! -x "$MT_OPT/bin/uv" ]; then
    curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" \
      | env UV_INSTALL_DIR="$MT_OPT/bin" UV_NO_MODIFY_PATH=1 sh >/dev/null \
      || { echo "FAIL: couldn't download uv ${UV_VERSION}"; exit 3; }
  fi
  UV_PYTHON_INSTALL_DIR="$MT_OPT/python" "$MT_OPT/bin/uv" venv --quiet --python "$PYTHON_VERSION" "$MT_DESK/venv" \
    || { echo "FAIL: couldn't install Python ${PYTHON_VERSION} with uv"; exit 3; }
  echo "ok: $("$MT_DESK/venv/bin/python" -V 2>&1) (installed into the desk with uv)"
fi

# 2. The config, once
if [ -f "$MT_DESK/config.toml" ]; then
  echo "skip: config.toml exists, left as it is"
else
  cp "$MT_CHECKOUT/config/config.template.toml" "$MT_DESK/config.toml"
  echo "ok: config.toml from the template"
fi

# 3. Safe starting state: rehearsal mode, building phase
[ -f "$MT_DESK/state/mode" ] && echo "skip: mode is $(cat "$MT_DESK/state/mode")" \
  || { echo rehearsal > "$MT_DESK/state/mode"; echo "ok: mode rehearsal (nothing posts)"; }
[ -f "$MT_DESK/state/phase" ] && echo "skip: phase is $(cat "$MT_DESK/state/phase")" \
  || { echo building > "$MT_DESK/state/phase"; echo "ok: phase building"; }

# 4. Stamp what's installed
commit=$(git -C "$MT_CHECKOUT" rev-parse --short HEAD 2>/dev/null || echo unknown)
echo "$BOT_RELEASE $commit" > "$MT_DESK/.bot-release"
echo "ok: release $BOT_RELEASE ($commit) from $MT_CHECKOUT"
