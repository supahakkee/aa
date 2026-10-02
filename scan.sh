#!/usr/bin/env bash
# Usage: ./scan.sh FILE [FILE ...] [--password PW] [--no-engines]
# Checks downloaded archives for malware without running anything inside them.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$DIR/setup.sh"
PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m scanner "$@"
