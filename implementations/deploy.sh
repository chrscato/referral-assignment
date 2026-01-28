#!/bin/bash
#
# Referral CRM - Deployment Script
# Run this to deploy code changes to production
#

# === CONFIG ===
REMOTE_USER="root"
REMOTE_HOST="159.223.104.254"
REMOTE_DIR="/srv/referral-crm"
TMUX_SESSION="referral_crm"
NGROK_SESSION="ngrok_tunnel"
NGROK_DOMAIN="crankly-tindery-vannesa.ngrok-free.dev"
APP_PORT="8000"
MAX_BACKUPS=10

echo "=========================================="
echo "  Referral CRM - Deployment"
echo "=========================================="
echo ""

# === STEP 1: Push local changes ===
echo "[1/5] Pushing local changes to GitHub..."
git add .

# Prompt for commit message
echo "Enter commit message (or press Enter for auto-generated):"
read commit_message

if [ -z "$commit_message" ]; then
    commit_message="Deploy at $(TZ='America/New_York' date '+%Y-%m-%d %H:%M:%S %Z')"
else
    commit_message="$commit_message - $(TZ='America/New_York' date '+%Y-%m-%d %H:%M:%S %Z')"
fi

git commit -m "$commit_message" || echo "Nothing to commit"
CURRENT_BRANCH=$(git branch --show-current)

# Ensure SSH remote
LOCAL_REMOTE=$(git remote get-url origin)
if [[ $LOCAL_REMOTE == https://* ]]; then
    echo "Switching to SSH remote..."
    REPO_NAME=$(echo $LOCAL_REMOTE | sed 's|https://github.com/||' | sed 's|\.git||')
    git remote set-url origin "git@github.com:${REPO_NAME}.git"
fi
REPO_SSH=$(git remote get-url origin)

# Add GitHub to known hosts if needed
if ! grep -q "github.com" ~/.ssh/known_hosts 2>/dev/null; then
    ssh-keyscan -H github.com >> ~/.ssh/known_hosts 2>/dev/null || true
fi

echo "Pushing to GitHub..."
git push origin $CURRENT_BRANCH

# === STEP 2: Copy configuration files ===
echo ""
echo "[2/5] Copying configuration files..."

if [ -f ".env" ]; then
    scp .env $REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/.env.new
    echo ".env file staged for deployment"
else
    echo "WARNING: No .env file found locally"
fi

# === STEP 3: Backup database on remote ===
echo ""
echo "[3/5] Backing up database..."

ssh $REMOTE_USER@$REMOTE_HOST << EOF
set -e
cd "$REMOTE_DIR"

# Create backup directory if not exists
mkdir -p backups

# Create timestamped backup if database exists
if [ -f "referral_crm.db" ]; then
    TIMESTAMP=\$(date '+%Y%m%d_%H%M%S')
    BACKUP_FILE="backups/referral_crm_\${TIMESTAMP}.db"
    cp referral_crm.db "\$BACKUP_FILE"
    echo "Database backed up to: \$BACKUP_FILE"

    # Rotate old backups (keep only last $MAX_BACKUPS)
    cd backups
    BACKUP_COUNT=\$(ls -1 referral_crm_*.db 2>/dev/null | wc -l)
    if [ "\$BACKUP_COUNT" -gt $MAX_BACKUPS ]; then
        ls -1t referral_crm_*.db | tail -n +\$(($MAX_BACKUPS + 1)) | xargs rm -f
        echo "Rotated old backups (keeping last $MAX_BACKUPS)"
    fi
    cd ..
else
    echo "No existing database to backup"
fi

# Backup current .env if exists
if [ -f ".env" ]; then
    cp .env .env.backup
    echo ".env backed up to .env.backup"
fi

# Move new .env into place
if [ -f ".env.new" ]; then
    mv .env.new .env
    echo ".env updated"
fi
EOF

# === STEP 4: Pull latest code and update dependencies ===
echo ""
echo "[4/5] Pulling latest code and updating dependencies..."

ssh $REMOTE_USER@$REMOTE_HOST << EOF
set -e
export PATH="\$HOME/.local/bin:\$PATH"

cd "$REMOTE_DIR"

# Add GitHub to known hosts
if ! grep -q "github.com" ~/.ssh/known_hosts 2>/dev/null; then
    ssh-keyscan -H github.com >> ~/.ssh/known_hosts 2>/dev/null || true
fi

# Update remote URL and pull
git remote set-url origin "$REPO_SSH"
git config pull.rebase false
git reset --hard HEAD
git pull origin $CURRENT_BRANCH --force || {
    echo "Pull failed, trying fetch + reset..."
    git fetch origin $CURRENT_BRANCH
    git reset --hard origin/$CURRENT_BRANCH
}

echo "Code updated successfully"

# Update dependencies
echo "Updating dependencies..."
source .venv/bin/activate

if command -v uv &> /dev/null; then
    uv pip install -r requirements.txt
else
    pip install -r requirements.txt
fi

echo "Dependencies updated"
EOF

# === STEP 5: Restart application ===
echo ""
echo "[5/5] Restarting application..."

ssh $REMOTE_USER@$REMOTE_HOST << EOF
set -e
export PATH="\$HOME/.local/bin:\$PATH"

cd "$REMOTE_DIR"

# Restart FastAPI app
echo "Restarting FastAPI application..."
tmux kill-session -t $TMUX_SESSION 2>/dev/null || true
sleep 1
tmux new-session -d -s $TMUX_SESSION "cd $REMOTE_DIR && source .venv/bin/activate && python run.py api"

# Ensure ngrok is running
if ! tmux has-session -t $NGROK_SESSION 2>/dev/null; then
    echo "Starting ngrok tunnel..."
    tmux new-session -d -s $NGROK_SESSION "ngrok http $APP_PORT --domain=$NGROK_DOMAIN"
fi

echo ""
echo "=========================================="
echo "  Deployment Complete!"
echo "=========================================="
echo ""
echo "Application: https://$NGROK_DOMAIN"
echo "API Docs: https://$NGROK_DOMAIN/docs"
echo ""
echo "Active sessions:"
tmux ls
EOF

echo ""
echo "=========================================="
echo "  Deployment Finished!"
echo "=========================================="
echo ""
echo "Your changes are now live at:"
echo "  https://$NGROK_DOMAIN"
