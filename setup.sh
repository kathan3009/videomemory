#!/usr/bin/env bash
# videomemory setup — one-shot installer.
#
# Usage:
#   ./setup.sh                # interactive: asks before installing anything
#   ./setup.sh --yes          # non-interactive: just do it
#   ./setup.sh --no-claude    # skip the `claude mcp add` step
#
# Idempotent. Safe to re-run.

set -euo pipefail

# ---------- cosmetics ----------
B=$(printf '\033[1m')   ; D=$(printf '\033[2m')
G=$(printf '\033[32m')  ; Y=$(printf '\033[33m')
R=$(printf '\033[31m')  ; C=$(printf '\033[36m')
N=$(printf '\033[0m')

say()  { printf "%s%s%s\n" "$B" "$*" "$N"; }
ok()   { printf "  %s✓%s %s\n" "$G" "$N" "$*"; }
warn() { printf "  %s!%s %s\n" "$Y" "$N" "$*"; }
err()  { printf "  %s✗%s %s\n" "$R" "$N" "$*"; }
hint() { printf "    %s%s%s\n" "$D" "$*" "$N"; }

YES=0
SKIP_CLAUDE=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y)        YES=1 ;;
    --no-claude)     SKIP_CLAUDE=1 ;;
    --help|-h)
      sed -n '2,9p' "$0" ; exit 0 ;;
  esac
done

confirm() {
  [[ $YES -eq 1 ]] && return 0
  read -r -p "  → $1 [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]]
}

OS="$(uname -s)"
ARCH="$(uname -m)"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
say "🎬  videomemory setup"
hint "$REPO_DIR  ·  $OS $ARCH"
echo ""

# ---------- 1. system deps ----------
say "1/4  system dependencies"

need_pkgs=()
command -v ffmpeg >/dev/null 2>&1 && ok "ffmpeg" || need_pkgs+=(ffmpeg)
command -v yt-dlp >/dev/null 2>&1 && ok "yt-dlp" || need_pkgs+=(yt-dlp)

if (( ${#need_pkgs[@]} > 0 )); then
  warn "missing: ${need_pkgs[*]}"
  if [[ "$OS" == "Darwin" ]]; then
    if ! command -v brew >/dev/null 2>&1; then
      err "Homebrew not installed."
      hint "Install brew first: https://brew.sh"
      exit 1
    fi
    if confirm "Install ${need_pkgs[*]} via brew?"; then
      brew install "${need_pkgs[@]}"
      ok "installed via brew"
    else
      err "cannot continue without ${need_pkgs[*]}"
      exit 1
    fi
  elif [[ "$OS" == "Linux" ]]; then
    if confirm "Install ${need_pkgs[*]} via apt-get?"; then
      sudo apt-get update -qq && sudo apt-get install -y "${need_pkgs[@]}"
      ok "installed via apt"
    else
      err "cannot continue without ${need_pkgs[*]}"
      exit 1
    fi
  else
    err "unsupported OS: $OS — install ${need_pkgs[*]} manually and re-run"
    exit 1
  fi
fi

# ---------- 2. uv ----------
say "2/4  uv (python project manager)"
if command -v uv >/dev/null 2>&1; then
  ok "uv $(uv --version | awk '{print $2}')"
else
  warn "uv not installed"
  if confirm "Install uv?"; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck disable=SC1091
    export PATH="$HOME/.local/bin:$PATH"
    ok "installed uv"
  else
    err "cannot continue without uv"
    exit 1
  fi
fi

# ---------- 3. python deps + models ----------
say "3/4  python deps + model warmup  (~1–3 min, one-time)"
cd "$REPO_DIR"
uv sync --quiet
ok "deps installed"

uv run --quiet videomemory setup >/dev/null 2>&1 || uv run videomemory setup
ok "models pre-pulled (~600 MB cached at ~/.cache/huggingface)"

# ---------- 4. wire into Claude Code ----------
if [[ $SKIP_CLAUDE -eq 0 ]] && command -v claude >/dev/null 2>&1; then
  say "4/4  register MCP server with Claude Code (user scope)"
  # Remove old registration if present (safe no-op otherwise)
  claude mcp remove videomemory -s user >/dev/null 2>&1 || true
  claude mcp add -s user videomemory -- \
    uv run --project "$REPO_DIR" videomemory mcp serve
  ok "registered as 'videomemory' (user scope)"
  hint "Codex / other clients: see examples/claude_desktop_config.json"
else
  say "4/4  Claude Code not detected — skipping MCP registration"
  hint "When you install Claude Code, run:"
  hint "  claude mcp add -s user videomemory -- uv run --project $REPO_DIR videomemory mcp serve"
fi

echo ""
say "done. try this in a new Claude Code session:"
echo ""
printf "  %s\"use videomemory to skip to the part of https://youtu.be/BM70fDqUo3c%s\n" "$C" "$N"
printf "  %swhere they explain the main idea\"%s\n" "$C" "$N"
echo ""
