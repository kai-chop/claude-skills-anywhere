#!/usr/bin/env sh
# qwen-skilled -- start Qwen Code with your Claude skills actually loadable.
#
# Same workspace rule as gemini-skilled.sh: the skill canon has to be inside the
# workspace or the body cannot be read.
#
# Auth: Qwen Code's own OAuth needs a browser. When no OAuth credentials exist yet,
# this falls back to an OpenAI-compatible endpoint using DASHSCOPE_API_KEY, exported
# for the duration of this process only -- exporting OPENAI_API_KEY permanently makes
# every other tool on the machine talk to that provider with that key.
#
# Override: SKILLS_CANON, QWEN_BIN, QWEN_BASE_URL, QWEN_MODEL.

set -e
CANON="${SKILLS_CANON:-$HOME/.claude/skills}"
BIN="${QWEN_BIN:-qwen}"

if [ -f "$HOME/.qwen/oauth_creds.json" ]; then
    exec "$BIN" --include-directories "$CANON" "$@"
fi

if [ -z "$DASHSCOPE_API_KEY" ]; then
    echo "qwen-skilled: no ~/.qwen/oauth_creds.json and no DASHSCOPE_API_KEY." >&2
    echo "Run \`qwen\` once in a real terminal to log in, or set DASHSCOPE_API_KEY." >&2
    exit 1
fi

OPENAI_API_KEY="$DASHSCOPE_API_KEY" \
OPENAI_BASE_URL="${QWEN_BASE_URL:-https://dashscope-intl.aliyuncs.com/compatible-mode/v1}" \
OPENAI_MODEL="${QWEN_MODEL:-qwen3-coder-plus}" \
exec "$BIN" --auth-type openai --include-directories "$CANON" "$@"
