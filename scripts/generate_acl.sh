#!/usr/bin/env bash

set -eu

cat >users.acl <<EOF
user default off nopass nocommands
user ${FALKORDB_USERNAME} on >${FALKORDB_PASSWORD} ~* &* +@all
EOF
