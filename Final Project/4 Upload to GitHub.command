#!/bin/bash
# Double-click: publishes cylinder-atlas as a PUBLIC GitHub repo via GitHub's web API (no git needed).
# Safe to re-run (updates changed files). Refuses to upload if .env or your real key is in the copy.
cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"; SRC="$ROOT/cylinder-atlas"
exec > >(tee "$ROOT/upload_log.txt") 2>&1
say()  { printf "\n\033[1m▶ %s\033[0m\n" "$1"; }
fail() { printf "\n\033[31m✖ %s\033[0m\n" "$1"; read -n1 -rp "Press any key to close…"; exit 1; }

DEFAULT_REPO="adethiru/cylinder-atlas"
read -rp "GitHub repo (owner/name) [Return for $DEFAULT_REPO]: " REPO
REPO="${REPO:-$DEFAULT_REPO}"; REPO="${REPO#https://github.com/}"; REPO="${REPO%.git}"; URL="https://github.com/$REPO"
for attempt in 1 2 3; do
  echo "Paste your GitHub token (ghp_… or github_pat_…, 'repo' scope) and press Return (nothing shows):"
  read -rs TOKEN; echo; TOKEN=$(printf "%s" "$TOKEN" | tr -d '[:space:]')
  CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" https://api.github.com/user)
  [ "$CODE" = "200" ] && { echo "✓ Token accepted"; break; }; echo "✖ Rejected (HTTP $CODE)"; TOKEN=""
done
[ -n "$TOKEN" ] || fail "No valid token."
AUTH="Authorization: Bearer $TOKEN"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "$AUTH" "https://api.github.com/repos/$REPO")
if [ "$CODE" = "404" ]; then
  say "Creating public repo $REPO"
  CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"name\":\"${REPO#*/}\",\"private\":false,\"description\":\"Cylinder Atlas - AI deal desk for an industrial gas distribution roll-up\"}" https://api.github.com/user/repos)
  [ "$CODE" = "201" ] || fail "Could not create repo (HTTP $CODE)."; sleep 2
fi
curl -s -o /dev/null -X PATCH -H "$AUTH" -H "Content-Type: application/json" -d '{"private":false}' "https://api.github.com/repos/$REPO"

say "Building clean copy"
STAGE="$ROOT/.upload_stage/cylinder-atlas"; rm -rf "$ROOT/.upload_stage"; mkdir -p "$STAGE"
rsync -a --exclude '.env' --exclude '__pycache__/' --exclude '*.pyc' --exclude '.DS_Store' --exclude '*.db-journal' "$SRC/" "$STAGE/"
[ -e "$STAGE/.env" ] && fail ".env in upload copy - refusing."
KEY=$(grep -m1 '^PORTKEY_API_KEY=' "$ROOT/.env" "$ROOT/../.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' [:space:]')
if [ -n "$KEY" ] && grep -rqaF -- "$KEY" "$STAGE"; then grep -rlaF -- "$KEY" "$STAGE"; fail "Your real key appears in the files above - refusing."; fi
echo "✓ No .env and no API key in the upload copy"

say "Uploading to $URL"
cd "$STAGE" || exit 1; API="https://api.github.com/repos/$REPO/contents"; OK=0; FAIL=0; TMP=$(mktemp)
while IFS= read -r -d '' f; do
  path="${f#./}"; enc=$(printf "%s" "$path" | sed 's/ /%20/g')
  sha=$(curl -s -H "$AUTH" "$API/$enc" | grep -m1 '"sha"' | sed -E 's/.*"sha": *"([^"]+)".*/\1/')
  { printf '{"message":"Update %s","content":"' "$path"; base64 -i "$f" | tr -d '\n'; printf '"'; [ -n "$sha" ] && printf ',"sha":"%s"' "$sha"; printf '}'; } > "$TMP"
  code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT -H "$AUTH" -H "Content-Type: application/json" --data-binary @"$TMP" "$API/$enc")
  if [ "$code" = "200" ] || [ "$code" = "201" ]; then OK=$((OK+1)); echo "  ✓ $path"; else FAIL=$((FAIL+1)); echo "  ✖ $path (HTTP $code)"; fi
done < <(find . -type f -print0 | sort -z)
rm -f "$TMP"; rm -rf "$ROOT/.upload_stage"
echo; echo "Uploaded $OK files, $FAIL failed."
printf "%s" "$URL" | pbcopy 2>/dev/null; echo "Repo: $URL (copied to clipboard)"
read -n1 -rp "Press any key to close…"
