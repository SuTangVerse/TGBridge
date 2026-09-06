#!/bin/sh
set -eu

# Copy once per agent, make it root:root mode 0755, and replace the command
# below with that agent's non-interactive CLI invocation. The CLI must read the
# complete prompt from stdin and print only its final answer to stdout.
exec env -i \
  HOME="/home/agent-a" \
  PATH="/usr/local/bin:/usr/bin:/bin" \
  LANG="C.UTF-8" \
  /usr/local/bin/your-agent-cli --non-interactive
