#!/usr/bin/env bash
# One-shot: import the fine-tuned router GGUF into Ollama and register it on
# the NexToken gateway as public model `nxt-router`.
#
#   GGUF=~/Downloads/nxt-router-q8_0.gguf bash train/wire_router.sh
#
# Afterwards set COPILOT_ROUTER_MODEL=nxt-router in the copilot-gateway launch
# profile and restart the copilot. Requires: ollama up, backend on :3100 with
# provider `ollama-local`, admin login enabled.
set -euo pipefail

GGUF="${GGUF:-$HOME/Downloads/nxt-router-q8_0.gguf}"
OLLAMA_NAME="${OLLAMA_NAME:-nxt-router-ft}"
PUBLIC_MODEL="${PUBLIC_MODEL:-nxt-router}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:3100}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-local-demo-admin-pass-2026}"

[ -f "$GGUF" ] || { echo "GGUF not found: $GGUF"; exit 1; }

jqpy() { python3 -c "import sys,json;print(json.load(sys.stdin)$1)"; }

echo "→ ollama import ($OLLAMA_NAME) — reuse qwen2.5's chat template/params"
WORK=$(mktemp -d)
ollama show --template qwen2.5:3b > "$WORK/template"
{
  echo "FROM $GGUF"
  echo "TEMPLATE \"\"\"$(cat "$WORK/template")\"\"\""
  echo 'PARAMETER stop "<|im_start|>"'
  echo 'PARAMETER stop "<|im_end|>"'
} > "$WORK/Modelfile"
ollama create "$OLLAMA_NAME" -f "$WORK/Modelfile"
rm -rf "$WORK"

echo "→ admin login"
AT=$(curl -s -X POST "$BACKEND_URL/api/admin/login" -H 'content-type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" | jqpy "['token']")

echo "→ find provider ollama-local"
PID=$(curl -s "$BACKEND_URL/api/admin/providers" -H "Authorization: Bearer $AT" \
  | python3 -c "import sys,json;print([p['id'] for p in json.load(sys.stdin) if p['name']=='ollama-local'][0])")
echo "   provider id=$PID"

echo "→ create model ($PUBLIC_MODEL → $OLLAMA_NAME)"
MID=$(curl -s -X POST "$BACKEND_URL/api/admin/models" -H "Authorization: Bearer $AT" -H 'content-type: application/json' \
  -d "{\"public_name\":\"$PUBLIC_MODEL\",\"upstream_model\":\"$OLLAMA_NAME\",\"provider_id\":$PID,\"input_price\":0.1,\"output_price\":0.3,\"input_cost\":0,\"output_cost\":0,\"endpoint_type\":\"chat\",\"supports_tool_calling\":true,\"active\":true}" | jqpy "['id']")
echo "   model id=$MID"

echo "→ create route"
curl -s -X POST "$BACKEND_URL/api/admin/models/$MID/routes" -H "Authorization: Bearer $AT" -H 'content-type: application/json' \
  -d "{\"provider_id\":$PID,\"upstream_model\":\"$OLLAMA_NAME\",\"priority\":10,\"weight\":100,\"active\":true}" >/dev/null

echo "→ smoke test through the gateway"
KEY=$(python3 -c "
import json
cfg = json.load(open('$HOME/Downloads/.claude/launch.json'))
for c in cfg['configurations']:
    if c['name'] == 'copilot-gateway':
        print([a.split('=',1)[1] for a in c['runtimeArgs'] if a.startswith('COPILOT_LLM_API_KEY=')][0])
")
curl -s -X POST "$BACKEND_URL/v1/chat/completions" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d "{\"model\":\"$PUBLIC_MODEL\",\"temperature\":0,\"messages\":[
    {\"role\":\"system\",\"content\":\"You are a supervisor. Choose exactly one worker for the sub-task. Reply with only the worker name.\"},
    {\"role\":\"user\",\"content\":\"ROUTE:: options=usage,billing,catalog,finance,help :: task=What API keys do I have?\"}]}" \
  | jqpy "['choices'][0]['message']['content']"

echo "DONE — set COPILOT_ROUTER_MODEL=$PUBLIC_MODEL in the copilot-gateway profile and restart."
