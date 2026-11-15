# SPDX-License-Identifier: GPL-3.0-or-later
# Shared by both images' entrypoints (POSIX sh, sourced).
#   panic_file_env NAME   if NAME_FILE is set, export NAME from that file (Docker / k8s secrets); the
#                         _FILE variant wins, as in panic_server.conf. Fails if the file is unreadable.
panic_file_env() {
    _pf_name="$1"
    eval "_pf_file=\${${_pf_name}_FILE:-}"
    if [ -n "$_pf_file" ]; then
        if [ ! -r "$_pf_file" ]; then
            echo "panic: ${_pf_name}_FILE is set but ${_pf_file} is not readable" >&2
            return 1
        fi
        eval "export ${_pf_name}=\"\$(cat \"\$_pf_file\")\""
    fi
    unset _pf_name _pf_file
}
