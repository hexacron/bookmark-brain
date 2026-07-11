#!/usr/bin/env bash
# Bookmark Brain — first-time setup
set -e

cd "$(dirname "$0")"

echo "→ creating venv"
python3 -m venv .venv
source .venv/bin/activate

echo "→ upgrading pip"
pip install --quiet --upgrade pip

echo "→ installing dependencies"
pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
    echo
    echo "Anthropic API key not found. Paste it now (will be saved to .env):"
    read -r -s KEY
    echo "ANTHROPIC_API_KEY=$KEY" > .env
    chmod 600 .env
    echo "→ saved to .env (mode 600)"
else
    echo "→ .env already exists, leaving it alone"
fi

echo
echo "Setup complete. Next:"
echo "  source .venv/bin/activate"
echo "  python brain.py enrich /path/to/bookmarks.html"
echo "  python brain.py serve"
