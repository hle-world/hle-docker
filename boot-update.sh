#!/bin/bash
# Sourced by run.sh (both images). Brings hle-client up to date at container
# start, unless disabled or pinned, without ever blocking or breaking startup.
#
#   HLE_AUTO_UPDATE=0       skip the update; the version baked into the image runs
#   HLE_CLIENT_VERSION=<v>  run exactly <v> (installed if missing, never upgraded past)
#
# Newer versions live in a versioned layout on the /data volume
# ($HLE_HOME/versions/<v>, $HLE_HOME/current -> versions/<v>), the same layout
# `hle update` and the dashboard self-update use, so they survive restarts and
# are not downloaded again on every boot. Each is a venv that sees the image's
# site-packages (fastapi, uvicorn) and overrides only hle-client.
#
# Any failure (offline, PyPI down, broken release) logs a warning and falls
# back to the newest version already available: never an error exit.
#
# After sourcing, HLE_BIN / HLE_PYTHON name the hle CLI and interpreter to run.

# shellcheck disable=SC2034  # HLE_BIN / HLE_PYTHON are read by run.sh
HLE_BIN="hle"
HLE_PYTHON="python3"

_hle_log() { echo "[hle] $*"; }

# Version of hle-client importable by the given interpreter ("" when unknown).
_hle_version_of() {
    "$1" -c "from importlib.metadata import version; print(version('hle-client'))" 2>/dev/null || true
}

# Latest published release; empty when the registry is unreachable.
_hle_latest_version() {
    python3 -c "
import json, urllib.request
with urllib.request.urlopen('https://pypi.org/pypi/hle-client/json', timeout=10) as r:
    print(json.load(r)['info']['version'])
" 2>/dev/null || true
}

# True when \$1 is a strictly newer version than \$2.
_hle_newer() {
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -n 1)" = "$1" ]
}

# Point HLE_BIN / HLE_PYTHON at the venv for version $1 when it is usable.
_hle_use_venv() {
    local dir="${HLE_HOME}/versions/$1"
    [ -x "${dir}/bin/hle" ] || return 1
    [ "$(_hle_version_of "${dir}/bin/python")" = "$1" ] || return 1
    export PATH="${dir}/bin:${PATH}"
    HLE_BIN="${dir}/bin/hle"
    HLE_PYTHON="${dir}/bin/python"
    return 0
}

# Run the version `current` points at, when it is newer than the baked one.
# Also used after exit code 75 (the agent swapped `current` and asked for a restart).
hle_activate_current() {
    local baked="$1" cur
    [ -L "${HLE_HOME}/current" ] || return 1
    cur="$(basename "$(readlink "${HLE_HOME}/current")")"
    if [ -n "${cur}" ] && _hle_newer "${cur}" "${baked}" && _hle_use_venv "${cur}"; then
        return 0
    fi
    return 1
}

_hle_install_version() {
    local v="$1" dir="${HLE_HOME}/versions/$1"
    mkdir -p "${HLE_HOME}/versions" || return 1
    rm -rf "${dir}"
    # Created in place: console-script shebangs embed the venv path.
    if python3 -m venv --system-site-packages "${dir}" >/dev/null 2>&1 \
        && timeout 120 "${dir}/bin/python" -m pip install --quiet --no-input \
            --disable-pip-version-check --timeout 10 --retries 1 \
            "hle-client==${v}" >/dev/null 2>&1 \
        && "${dir}/bin/hle" --version >/dev/null 2>&1 \
        && "${dir}/bin/python" -c "import hle_client, fastapi, uvicorn" >/dev/null 2>&1 \
        && [ "$(_hle_version_of "${dir}/bin/python")" = "${v}" ]; then
        ln -sfn "versions/${v}" "${HLE_HOME}/current.tmp" && mv -T "${HLE_HOME}/current.tmp" "${HLE_HOME}/current"
        return 0
    fi
    rm -rf "${dir}"
    return 1
}

hle_boot_update() {
    export HLE_HOME="${HLE_HOME:-/data/hle}"
    local baked target pinned="" decision
    baked="$(_hle_version_of python3)"
    baked="${baked:-unknown}"

    case "$(echo "${HLE_AUTO_UPDATE:-1}" | tr '[:upper:]' '[:lower:]')" in
        0 | false | no | off)
            _hle_log "hle-client installed=${baked} target=n/a decision=skip (HLE_AUTO_UPDATE disabled)"
            return 0
            ;;
    esac

    if [ -n "${HLE_CLIENT_VERSION:-}" ]; then
        target="${HLE_CLIENT_VERSION#v}"
        pinned=1
    else
        target="$(_hle_latest_version)"
    fi

    if [ -z "${target}" ]; then
        if hle_activate_current "${baked}"; then
            decision="offline, using ${HLE_BIN%/bin/hle} from ${HLE_HOME}"
        else
            decision="offline, using baked version"
        fi
        _hle_log "WARNING: could not look up the latest hle-client; hle-client installed=${baked} target=unknown decision=${decision}"
        return 0
    fi

    if [ "${target}" = "${baked}" ]; then
        decision="keep (baked version is the target)"
    elif _hle_use_venv "${target}"; then
        decision="switch to ${target} already on /data"
    elif [ -z "${pinned}" ] && ! _hle_newer "${target}" "${baked}"; then
        # Registry lags behind the image (fresh image, PyPI not yet showing it).
        decision="keep (baked version is not older than ${target})"
    elif _hle_install_version "${target}" && _hle_use_venv "${target}"; then
        decision="installed ${target} on /data"
    else
        if [ -z "${pinned}" ] && hle_activate_current "${baked}"; then
            decision="WARNING: install of ${target} failed, using ${HLE_BIN%/bin/hle} from ${HLE_HOME}"
        else
            decision="WARNING: install of ${target} failed, using baked ${baked}"
        fi
    fi
    _hle_log "hle-client installed=${baked} target=${target}${pinned:+ (pinned)} decision=${decision}"
    return 0
}
