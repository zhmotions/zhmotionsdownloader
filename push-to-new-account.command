#!/usr/bin/env bash
# Push to NEW GitHub account (zhmotions)
# Double-click to run.

set -e
cd "$(dirname "$0")"

NEW_USER="zhmotions"
NEW_REPO="zhmotionsdownloader"

echo ""
echo " ============================================================"
echo "   ZH Downloader — Push to new account ($NEW_USER)"
echo " ============================================================"
echo ""

# 1. gh CLI required
if ! command -v gh >/dev/null 2>&1; then
    echo "GitHub CLI missing. Install with: brew install gh"
    exit 1
fi

# 2. Login to new account if not already
echo " [1/6] Checking auth for $NEW_USER..."
if ! gh auth status 2>&1 | grep -q "Logged in to github.com account $NEW_USER"; then
    echo " [!] Not logged in as $NEW_USER. Opening browser to authenticate..."
    gh auth login --hostname github.com --git-protocol https --web
fi

# Switch to new account
gh auth switch -u "$NEW_USER" 2>/dev/null || true

# 3. Create repo if doesn't exist
echo ""
echo " [2/6] Checking repo $NEW_USER/$NEW_REPO..."
if ! gh repo view "$NEW_USER/$NEW_REPO" >/dev/null 2>&1; then
    echo " [!] Repo doesn't exist. Creating private repo..."
    gh repo create "$NEW_USER/$NEW_REPO" --private --description "ZH Downloader for ZH Motions students"
else
    echo " [OK] Repo exists."
fi

# 4. Update local remote
echo ""
echo " [3/6] Setting remote to new account..."
git remote set-url origin "https://github.com/$NEW_USER/$NEW_REPO.git"

# 5. Update URL references in code
echo ""
echo " [4/6] Updating URL references in code/docs..."
find . \( -name "*.py" -o -name "*.md" -o -name "*.html" -o -name "*.txt" -o -name "*.yml" \) \
       -not -path "./.git/*" -not -path "./.venv/*" \
       -exec sed -i '' "s|zhmotions/zhmotionsdownloader|$NEW_USER/$NEW_REPO|g" {} \;

git config user.email "zhmotions@gmail.com" 2>/dev/null || true
git config user.name  "ZH Motions"                2>/dev/null || true

git add -A
if ! git diff --cached --quiet; then
    git commit -m "chore: switch to new account ($NEW_USER/$NEW_REPO)"
fi

# 6. Push everything
echo ""
echo " [5/6] Pushing code + tags..."
git push origin main --force
git push origin --tags --force

# 7. Configure Actions permissions
echo ""
echo " [6/6] Configuring Actions permissions..."
gh api -X PUT "/repos/$NEW_USER/$NEW_REPO/actions/permissions/workflow" \
    -F default_workflow_permissions=write -F can_approve_pull_request_reviews=true \
    >/dev/null 2>&1 || true

echo ""
echo " ============================================================"
echo "   DONE — pushed to https://github.com/$NEW_USER/$NEW_REPO"
echo "   Actions: https://github.com/$NEW_USER/$NEW_REPO/actions"
echo "   Releases: https://github.com/$NEW_USER/$NEW_REPO/releases"
echo " ============================================================"
echo ""

read -p "Press Enter to close..."
