#!/bin/bash
# One-time setup: put the recom bot on GitHub Actions so it runs while the Mac is off.
# Run it in the Terminal: bash setup_cloud.sh      (the secrets are read from your local .env, never printed)
set -e
cd "$(dirname "$0")"
ENV="../../trading-safety/.env"
[ -f "$ENV" ] || ENV="$(cd .. && pwd)/../trading-safety/.env"

export PATH="$HOME/.local/bin:$PATH"
command -v gh >/dev/null || { echo "The GitHub CLI (gh) is missing: ask Claude to install it."; exit 1; }
# No yes/no questions: only the one-time code to paste in the browser.
gh auth status >/dev/null 2>&1 || GH_PROMPT_DISABLED=1 gh auth login --web --git-protocol https --hostname github.com
gh auth setup-git

REPO="recom-bot"
if ! gh repo view "$REPO" >/dev/null 2>&1; then
  gh repo create "$REPO" --public --description "Telegram recom bot (gold + oil)" >/dev/null
fi
# Public: GitHub Actions minutes are free and unlimited (a private repo runs out in about 2 days). The keys stay in
# encrypted repository secrets and are never committed; only the code and the call history (state/) are visible.
gh repo edit "$REPO" --visibility public --accept-visibility-change-consequences >/dev/null 2>&1 || true
USER_NAME="$(gh api user --jq .login)"
[ -d .git ] || git init -q -b main
git add -A
git -c user.name=recom-bot -c user.email=bot@users.noreply.github.com commit -qm "recom bot" 2>/dev/null || true
git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$USER_NAME/$REPO.git"
git push -u origin main

for K in TELEGRAM_BOT_TOKEN TELEGRAM_RECOM_ID TELEGRAM_CHAT_ID BYBIT_DEMO_KEY BYBIT_DEMO_SECRET; do
  grep "^$K=" "$ENV" | cut -d= -f2- | tr -d '\r\n' | gh secret set "$K" --repo "$USER_NAME/$REPO" >/dev/null
done
gh workflow run recom --repo "$USER_NAME/$REPO" >/dev/null 2>&1 || true
echo ""
echo "Done. The bot now runs in the cloud every 5 minutes:  https://github.com/$USER_NAME/$REPO/actions"
echo "Tell Claude 'cloud is running' and the jobs on the Mac will be switched off so nothing posts twice."
