# Referral CRM - Production Deployment Plan

## Overview

Deploy the Referral CRM application to a DigitalOcean VM using:
- Git-based code deployments (push locally, pull on VM)
- ngrok for HTTPS tunneling
- SQLite database with version control
- tmux for persistent process management

## Configuration

| Setting | Value |
|---------|-------|
| Remote Host | `159.223.104.254` |
| Remote User | `root` |
| Remote Directory | `/srv/referral-crm` |
| ngrok Auth Token | `rd_33Dt8pST9x8iMn27Wv6atGGW5cc` |
| ngrok Domain | `crankly-tindery-vannesa.ngrok-free.dev` |
| App Port | `8000` |
| tmux Session | `referral_crm` |

---

## Phase 1: Initial VM Setup (One-Time)

Run `startup.sh` on your local machine to bootstrap the VM.

### What startup.sh does:
1. Installs system dependencies (git, python3, uv, tmux, ngrok)
2. Configures ngrok with auth token and domain
3. Clones the repository to `/srv/referral-crm`
4. Creates Python virtual environment
5. Installs Python dependencies
6. Copies `.env` file from local machine
7. Initializes the SQLite database
8. Starts the FastAPI app in a tmux session
9. Starts ngrok tunnel in a separate tmux session

### Usage:
```bash
./startup.sh
```

---

## Phase 2: Code Deployments (Ongoing)

Run `deploy.sh` locally for code updates.

### What deploy.sh does:
1. **Local**: Commits and pushes changes to GitHub
2. **Remote**: Creates timestamped backup of database
3. **Remote**: Pulls latest code from GitHub
4. **Remote**: Copies `.env` from local (preserves secrets)
5. **Remote**: Updates Python dependencies
6. **Remote**: Restarts the FastAPI app in tmux

### Usage:
```bash
./deploy.sh
```

---

## Phase 3: Database Versioning Strategy

### Backup Policy:
- **Before each deploy**: Automatic timestamped backup
- **Location**: `/srv/referral-crm/backups/`
- **Naming**: `referral_crm_YYYYMMDD_HHMMSS.db`
- **Retention**: Keep last 10 backups

### Restore Procedure:
```bash
# SSH into VM
ssh root@159.223.104.254

# List available backups
ls -la /srv/referral-crm/backups/

# Restore specific backup
cp /srv/referral-crm/backups/referral_crm_20250128_120000.db /srv/referral-crm/referral_crm.db

# Restart app
tmux kill-session -t referral_crm
cd /srv/referral-crm && source .venv/bin/activate && python run.py api
```

### .env Versioning:
- `.env` file copied from local on each deploy
- Previous `.env` backed up to `.env.backup` before overwrite
- Never committed to git (in .gitignore)

---

## File Structure on VM

```
/srv/referral-crm/
├── .venv/                  # Python virtual environment
├── .env                    # Environment variables (not in git)
├── backups/                # Database backups
│   ├── referral_crm_20250128_120000.db
│   └── ...
├── referral_crm.db         # Active SQLite database
├── attachments/            # Email attachments
├── src/                    # Application source code
│   └── referral_crm/
├── run.py                  # Application entry point
└── requirements.txt
```

---

## Accessing the Application

| Service | URL |
|---------|-----|
| Web UI | https://crankly-tindery-vannesa.ngrok-free.dev |
| API Docs | https://crankly-tindery-vannesa.ngrok-free.dev/docs |

---

## Troubleshooting

### Check App Status:
```bash
ssh root@159.223.104.254 "tmux ls"
```

### View App Logs:
```bash
ssh root@159.223.104.254 "tmux attach -t referral_crm"
# Press Ctrl+B then D to detach
```

### View ngrok Status:
```bash
ssh root@159.223.104.254 "tmux attach -t ngrok_tunnel"
```

### Manual App Restart:
```bash
ssh root@159.223.104.254 << 'EOF'
tmux kill-session -t referral_crm 2>/dev/null
cd /srv/referral-crm && source .venv/bin/activate
tmux new-session -d -s referral_crm "python run.py api"
EOF
```

### Manual ngrok Restart:
```bash
ssh root@159.223.104.254 << 'EOF'
tmux kill-session -t ngrok_tunnel 2>/dev/null
tmux new-session -d -s ngrok_tunnel "ngrok http 8000 --domain=crankly-tindery-vannesa.ngrok-free.dev"
EOF
```

---

## Scripts

| Script | Purpose |
|--------|---------|
| `startup.sh` | One-time VM setup and initial deployment |
| `deploy.sh` | Ongoing code deployments |

Both scripts are located in `implementations/` directory.
