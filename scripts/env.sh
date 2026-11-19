# env.sh: sourced by the other scripts. Paths on the Grok Bot computer, which keeps /workspace between
# sessions but not installed packages. Set MT_DESK to try the bot somewhere else (a laptop, CI).
MT_CHECKOUT=${MT_CHECKOUT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
MT_DESK=${MT_DESK:-/workspace/monsterten-desk}
MT_OPT="$MT_DESK/opt"
# shellcheck source=../pins.env
. "$MT_CHECKOUT/pins.env"
if [ -z "${MT_PYTHON:-}" ]; then
  if [ -x "$MT_DESK/venv/bin/python" ]; then
    MT_PYTHON="$MT_DESK/venv/bin/python"     # installed by install.sh when the computer had no Python 3.11+
  else
    MT_PYTHON=$(command -v python3 || true)
  fi
fi
export MT_CHECKOUT MT_DESK MT_OPT MT_PYTHON
