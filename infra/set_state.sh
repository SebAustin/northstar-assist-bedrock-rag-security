#!/usr/bin/env bash
# Record a resource ID created in the console, e.g.: infra/set_state.sh KB_ID ABCDEFGHIJ
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
[[ $# -eq 2 ]] || die "usage: $0 KEY VALUE"
[[ "$1" =~ ^[A-Z_]+$ ]] || die "KEY must be UPPER_SNAKE_CASE"
state_set "$1" "$2"
log "saved $1"
