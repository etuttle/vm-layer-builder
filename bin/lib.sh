die() { echo "$@"; exit 1; }

trap_add() {
  trap_add_cmd=$1; shift || die "${FUNCNAME} usage error"
  for trap_add_name in "$@"; do
    trap -- "$(
      printf '%s\n' "${trap_add_cmd}"
      extract_trap_cmd() { printf '%s' "$3"; }
      eval "extract_trap_cmd $(trap -p "${trap_add_name}")"
    )" "${trap_add_name}" \
      || die "unable to add to trap ${trap_add_name}"
  done
}

trap_add_last() {
  trap_add_cmd=$1; shift || die "${FUNCNAME} usage error"
  for trap_add_name in "$@"; do
    trap -- "$(
      extract_trap_cmd() { printf '%s' "$3"; }
      eval "extract_trap_cmd $(trap -p "${trap_add_name}")"
      printf '\n%s' "${trap_add_cmd}"
    )" "${trap_add_name}" \
      || die "unable to add to trap ${trap_add_name}"
  done
}