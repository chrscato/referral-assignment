#!/bin/bash
#
# Referral CRM - Initial VM Setup Script
# Run this ONCE to bootstrap the production environment
#

set -e  # Exit on error

# === CONFIG ===
REMOTE_USER="root"
REMOTE_HOST="159.223.104.254"
REMOTE_DIR="/srv/referral-crm"
TMUX_SESSION="referral_crm"
NGROK_SESSION="ngrok_tunnel"
NGROK_AUTH_TOKEN="rd_33Dt8pST9x8iMn27Wv6atGGW5cc"
NGROK_DOMAIN="crankly-tindery-vannesa.ngrok-free.dev"
APP_PORT="8000"

echo "=========================================="
echo "  Referral CRM - Initial VM Setup"
echo "=========================================="
echo ""

# === STEP 1: Get the Git repository URL ===
echo "[1/6] Getting repository information..."

# Ensure local remote is using SSH
LOCAL_REMOTE=$(git remote get-url origin)
if [[ $LOCAL_REMOTE == https://* ]]; then
    echo "Switching local remote from HTTPS to SSH..."
    REPO_NAME=$(echo $LOCAL_REMOTE | sed 's|https://github.com/||' | sed 's|\.git||')
    git remote set-url origin "git@github.com:${REPO_NAME}.git"
fi
REPO_SSH=$(git remote get-url origin)
echo "Repository: $REPO_SSH"

# === STEP 2: Push any local changes first ===
echo ""
echo "[2/6] Pushing local changes to GitHub..."
git add .
CURRENT_BRANCH=$(git branch --show-current)
git commit -m "Pre-deployment commit - $(TZ='America/New_York' date '+%Y-%m-%d %H:%M:%S %Z')" || echo "Nothing to commit"
git push origin $CURRENT_BRANCH || echo "Push failed or nothing to push"

# === STEP 3: Copy .env file to a temp location for transfer ===
echo ""
echo "[3/6] Preparing configuration files..."
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found locally!"
    echo "Please create a .env file with your configuration before running this script."
    exit 1
fi

# === STEP 4: Setup VM environment ===
echo ""
echo "[4/6] Setting up VM environment..."

ssh $REMOTE_USER@$REMOTE_HOST << 'ENDSSH'
set -e

echo "Installing system dependencies..."

# Update package lists
apt-get update -qq

# Install required packages
apt-get install -y -qq git python3 python3-venv tmux curl

# Install uv if not present
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install ngrok if not present
if ! command -v ngrok &> /dev/null; then
    echo "Installing ngrok..."
    curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
        | tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
    echo "deb https://ngrok-agent.s3.amazonaws.com buster main" \
        | tee /etc/apt/sources.list.d/ngrok.list
    apt-get update -qq
    apt-get install -y -qq ngrok
fi

echo "System dependencies installed!"
ENDSSH

# === STEP 5: Configure ngrok and clone repository ===
echo ""
echo "[5/6] Configuring ngrok and cloning repository..."

ssh $REMOTE_USER@$REMOTE_HOST << EOF
set -e
export PATH="\$HOME/.local/bin:\$PATH"

# Configure ngrok
echo "Configuring ngrok..."
ngrok config add-authtoken $NGROK_AUTH_TOKEN

# Add GitHub to known hosts
if ! grep -q "github.com" ~/.ssh/known_hosts 2>/dev/null; then
    echo "Adding GitHub to known hosts..."
    ssh-keyscan -H github.com >> ~/.ssh/known_hosts 2>/dev/null || true
fi

# Clone repository if not exists
if [ ! -d "$REMOTE_DIR/.git" ]; then
    echo "Cloning repository..."
    rm -rf "$REMOTE_DIR"
    git clone "$REPO_SSH" "$REMOTE_DIR"
else
    echo "Repository already exists, pulling latest..."
    cd "$REMOTE_DIR"
    git remote set-url origin "$REPO_SSH"
    git fetch origin
    git reset --hard origin/$CURRENT_BRANCH
fi

# Create backups directory
mkdir -p "$REMOTE_DIR/backups"

# Create attachments directory
mkdir -p "$REMOTE_DIR/attachments"

# Setup Python virtual environment
cd "$REMOTE_DIR"
echo "Setting up Python virtual environment..."

if command -v uv &> /dev/null; then
    uv venv --python 3.11 || uv venv
    source .venv/bin/activate
    echo "Installing dependencies with uv..."
    uv pip install -r requirements.txt
else
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
fi

echo "Python environment setup complete!"
EOF

# === STEP 6: Copy .env and start services ===
echo ""
echo "[6/6] Copying configuration and starting services..."

# Copy .env file
scp .env $REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/.env
echo ".env file copied successfully"

# Start the application and ngrok
ssh $REMOTE_USER@$REMOTE_HOST << EOF
set -e
export PATH="\$HOME/.local/bin:\$PATH"

cd "$REMOTE_DIR"

# Kill any existing sessions
tmux kill-session -t $TMUX_SESSION 2>/dev/null || true
tmux kill-session -t $NGROK_SESSION 2>/dev/null || true

# Start the FastAPI application
echo "Starting FastAPI application..."
tmux new-session -d -s $TMUX_SESSION "cd $REMOTE_DIR && source .venv/bin/activate && python run.py api"

# Wait a moment for the app to start
sleep 3

# Start ngrok tunnel
echo "Starting ngrok tunnel..."
tmux new-session -d -s $NGROK_SESSION "ngrok http $APP_PORT --domain=$NGROK_DOMAIN"

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "Application URL: https://$NGROK_DOMAIN"
echo "API Docs: https://$NGROK_DOMAIN/docs"
echo ""
echo "tmux sessions:"
tmux ls
echo ""
echo "To view logs: ssh $REMOTE_USER@$REMOTE_HOST 'tmux attach -t $TMUX_SESSION'"
echo "To view ngrok: ssh $REMOTE_USER@$REMOTE_HOST 'tmux attach -t $NGROK_SESSION'"
EOF

echo ""
echo "=========================================="
echo "  Local Setup Complete!"
echo "=========================================="
echo ""
echo "Your Referral CRM is now live at:"
echo "  https://$NGROK_DOMAIN"
echo ""
echo "For future deployments, use: ./deploy.sh"
