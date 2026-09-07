#!/usr/bin/env bash
set -euo pipefail

container=davincibox
python=python3
args=()
while (($#)); do
    case "$1" in
        --container|--python)
            if (($# < 2)) || [[ -z "$2" ]]; then
                echo "Missing value for $1" >&2; exit 2
            fi
            if [[ "$1" == --container ]]; then container=$2; else python=$2; fi
            shift 2 ;;
        --dry-run) args+=("$1"); shift ;;
        --help|-h)
            echo "Usage: bash scripts/install-resolve-linux.sh [--container NAME] [--python PATH] [--dry-run]"
            echo "Run from the host or a development Distrobox. Defaults: davincibox, python3."
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
runner=(distrobox)
if [[ -f /run/.containerenv ]] && command -v distrobox-host-exec >/dev/null; then
    runner=(distrobox-host-exec distrobox)
elif ! command -v distrobox >/dev/null; then
    echo "Distrobox is required. Run this command from your Bazzite host terminal." >&2
    exit 1
fi

exec "${runner[@]}" enter -n "$container" -- "$python" \
    "$project_root/scripts/install_resolve_linux.py" "${args[@]}"
