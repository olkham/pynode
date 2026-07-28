#!/bin/bash
set -e

# Ensure bind-mounted directories are writable by appuser (uid 1000).
# docker-compose mounts host directories that may be owned by root.
for dir in /app/workflows /app/workflows/services /app/logs; do
    mkdir -p "$dir"
    chown -R 1000:1000 "$dir" 2>/dev/null || true
done

# Drop privileges and exec the CMD
exec gosu appuser "$@"
