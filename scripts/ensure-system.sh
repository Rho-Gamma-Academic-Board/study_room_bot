#!/bin/bash
# Install OS packages needed before setup (git, python3, venv).
# Safe to run repeatedly. Used by install.sh and setup.sh.

set -euo pipefail

run_privileged() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    printf 'error: need root or sudo to install system packages\n' >&2
    return 1
  fi
}

is_apt_linux() {
  [[ "$(uname -s)" == "Linux" ]] && command -v apt-get >/dev/null 2>&1
}

python_venv_ready() {
  command -v python3 >/dev/null 2>&1 \
    && python3 -c "import venv, ensurepip" >/dev/null 2>&1
}

apt_pkg_installed() {
  dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "install ok installed"
}

ensure_apt_packages() {
  local -a required=(ca-certificates git python3 python3-pip python3-venv)
  local -a missing=()
  local pkg

  for pkg in "${required[@]}"; do
    apt_pkg_installed "$pkg" || missing+=("$pkg")
  done

  if command -v python3 >/dev/null 2>&1 && ! python_venv_ready; then
    for pkg in python3-venv python3-pip; do
      apt_pkg_installed "$pkg" || missing+=("$pkg")
    done
  fi

  if ((${#missing[@]} == 0)); then
    return 0
  fi

  # Deduplicate package names.
  local -a unique=()
  local seen="" u
  for pkg in "${missing[@]}"; do
    [[ " $seen " == *" $pkg "* ]] && continue
    seen+=" $pkg"
    unique+=("$pkg")
  done

  printf '==> Installing system packages: %s\n' "${unique[*]}"
  run_privileged apt-get update -qq
  DEBIAN_FRONTEND=noninteractive run_privileged apt-get install -y "${unique[@]}"
}

ensure_macos_packages() {
  if ! command -v git >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
      printf '==> Installing git via Homebrew\n'
      brew install git
    else
      printf 'error: git is required. Install Xcode Command Line Tools: xcode-select --install\n' >&2
      return 1
    fi
  fi

  if python_venv_ready; then
    return 0
  fi

  if command -v brew >/dev/null 2>&1; then
    printf '==> Installing Python via Homebrew\n'
    brew install python3
    return 0
  fi

  if ! xcode-select -p >/dev/null 2>&1; then
    printf 'error: Python 3 is required. Run: xcode-select --install\n' >&2
    return 1
  fi

  printf 'error: Python 3 with venv is required. Install Homebrew, then: brew install python3\n' >&2
  return 1
}

# Minimal bootstrap before git clone (install.sh only needs git).
ensure_git_for_clone() {
  if command -v git >/dev/null 2>&1; then
    return 0
  fi

  if is_apt_linux; then
    printf '==> Installing git (needed to clone the repo)\n'
    run_privileged apt-get update -qq
    DEBIAN_FRONTEND=noninteractive run_privileged apt-get install -y ca-certificates git
    return 0
  fi

  if [[ "$(uname -s)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    printf '==> Installing git via Homebrew\n'
    brew install git
    return 0
  fi

  printf 'error: git is required but could not be installed automatically\n' >&2
  return 1
}

ensure_system_packages() {
  case "$(uname -s)" in
    Linux)
      if is_apt_linux; then
        ensure_apt_packages
      else
        command -v git >/dev/null 2>&1 || {
          printf 'error: git is required\n' >&2
          return 1
        }
        python_venv_ready || {
          printf 'error: python3 with venv is required (Debian/Ubuntu/Raspberry Pi OS recommended)\n' >&2
          return 1
        }
      fi
      ;;
    Darwin)
      ensure_macos_packages
      ;;
    *)
      printf 'error: unsupported OS: %s\n' "$(uname -s)" >&2
      return 1
      ;;
  esac

  command -v git >/dev/null 2>&1 || {
    printf 'error: git is required\n' >&2
    return 1
  }
  python_venv_ready || {
    printf 'error: python3 venv module is still missing after system install\n' >&2
    return 1
  }
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  ensure_system_packages
fi
