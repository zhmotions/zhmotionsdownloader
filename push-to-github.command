#!/usr/bin/env bash
# Double-click this file to push code to GitHub.
# First run: installs gh CLI + auth (browser opens). Future runs: just push.

set -e
cd "$(dirname "$0")"

echo "=== ZH Downloader: Push to GitHub ==="
echo

# 1. Install Homebrew if missing
if ! command -v brew >/dev/null 2>&1; then
    echo "Installing Homebrew (needed for gh CLI)..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
fi

# 2. Install gh CLI if missing
if ! command -v gh >/dev/null 2>&1; then
    echo "Installing GitHub CLI..."
    brew install gh
fi

# 3. Auth if not logged in
if ! gh auth status >/dev/null 2>&1; then
    echo
    echo "Login to GitHub (browser will open)..."
    gh auth login --hostname github.com --git-protocol https --web
fi

# 4. Ensure git config
git config user.email "zhmotionspanel@gmail.com" 2>/dev/null || true
git config user.name  "ZH Motions"                2>/dev/null || true

# 5. Show what will push
echo
echo "=== Pending push ==="
git log origin/main..HEAD --oneline 2>/dev/null || echo "(no commits ahead of remote)"
echo

read -p "Push to main? [y/N] " ans
if [[ "$ans" != "y" && "$ans" != "Y" ]]; then
    echo "Cancelled."
    exit 0
fi

# 6. Push
git push origin main

# 7. Tag + push tag for release
read -p "Create release tag v4.0.0? (triggers installer build) [y/N] " ans
if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
    git tag -f v4.0.0
    git push origin v4.0.0 --force
    echo
    echo "Release in progress: https://github.com/zhmotions/zhmotionsdownloader/actions"
fi

echo
echo "Done. Press Enter to close."
read
