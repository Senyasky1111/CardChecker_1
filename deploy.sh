#!/bin/bash
# ============================================================
# CardCheck Backend — Hetzner Cloud Deployment Script
# ============================================================
#
# PREREQUISITES:
#   1. Hetzner Cloud account (https://console.hetzner.cloud)
#   2. SSH key added to Hetzner
#   3. hcloud CLI installed: brew install hcloud / choco install hcloud
#
# USAGE:
#   1. Create server:   ./deploy.sh create
#   2. Setup server:    ./deploy.sh setup
#   3. Deploy app:      ./deploy.sh deploy
#   4. View logs:       ./deploy.sh logs
#   5. SSH into server: ./deploy.sh ssh
#   6. Destroy server:  ./deploy.sh destroy
#
# ============================================================

set -euo pipefail

# ── DEPRECATED for routine code deploys ──────────────────────
# './deploy.sh deploy' clobbers the whole project and dies if the SSH session drops
# mid-build. Use the robust code-only script instead (detached build, rollback, smoke).
if [[ "${1:-}" == "deploy" ]]; then
  echo "deploy.sh deploy is deprecated. Use:  ./scripts/deploy_prod.sh"
  echo "(code-only deploy, survives SSH drops, captures a rollback tag)"
  exit 1
fi

# ── Configuration ────────────────────────────────────────────
SERVER_NAME="cardcheck-api"
SERVER_TYPE="ccx23"          # 4 vCPU, 16GB RAM, x86 (€15.29/mo)
# SERVER_TYPE="cax21"        # 4 vCPU, 8GB RAM, ARM (€3.99/mo) — cheaper but needs ARM Docker image
IMAGE="ubuntu-24.04"
LOCATION="fsn1"              # Falkenstein, Germany
DOMAIN=""                    # Set to your domain, e.g. api.cardcheck.app
SSH_KEY_NAME="default"       # Name of your SSH key in Hetzner

# Will be set dynamically
SERVER_IP=""

# ── Helpers ──────────────────────────────────────────────────
red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
blue()  { echo -e "\033[34m$1\033[0m"; }

get_ip() {
    SERVER_IP=$(hcloud server ip "$SERVER_NAME" 2>/dev/null || true)
    if [ -z "$SERVER_IP" ]; then
        red "Server '$SERVER_NAME' not found. Run: ./deploy.sh create"
        exit 1
    fi
}

# ── Commands ─────────────────────────────────────────────────

cmd_create() {
    blue "Creating Hetzner server: $SERVER_NAME ($SERVER_TYPE)..."
    hcloud server create \
        --name "$SERVER_NAME" \
        --type "$SERVER_TYPE" \
        --image "$IMAGE" \
        --location "$LOCATION" \
        --ssh-key "$SSH_KEY_NAME"

    SERVER_IP=$(hcloud server ip "$SERVER_NAME")
    green "Server created! IP: $SERVER_IP"
    echo ""
    echo "Next steps:"
    echo "  1. Point your domain to $SERVER_IP (A record)"
    echo "  2. Run: ./deploy.sh setup"
}

cmd_setup() {
    get_ip
    blue "Setting up server at $SERVER_IP..."

    ssh -o StrictHostKeyChecking=no root@"$SERVER_IP" bash <<'SETUP_EOF'
        set -e

        # Update system
        apt-get update && apt-get upgrade -y

        # Install Docker
        curl -fsSL https://get.docker.com | sh

        # Install Docker Compose plugin
        apt-get install -y docker-compose-plugin

        # Install Caddy (reverse proxy + auto HTTPS)
        apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
        apt-get update && apt-get install -y caddy

        # Create app directory
        mkdir -p /opt/cardcheck

        echo "✅ Setup complete!"
SETUP_EOF

    green "Server setup done! Run: ./deploy.sh deploy"
}

cmd_deploy() {
    get_ip
    blue "Deploying to $SERVER_IP..."

    # Sync project files (excluding images, venv, etc.)
    rsync -avz --progress \
        --exclude='venv/' \
        --exclude='.venv/' \
        --exclude='data/cardmarket/images/' \
        --exclude='data/cardmarket/_browser_profile/' \
        --exclude='data/cardmarket/_cdp_profile/' \
        --exclude='data/cardmarket/debug_*' \
        --exclude='data/cardmarket/test_*' \
        --exclude='runs/' \
        --exclude='notebooks/' \
        --exclude='__pycache__/' \
        --exclude='.git/' \
        --exclude='.claude/' \
        --exclude='*.pyc' \
        ./ root@"$SERVER_IP":/opt/cardcheck/

    # Build and start
    ssh root@"$SERVER_IP" bash <<DEPLOY_EOF
        set -e
        cd /opt/cardcheck

        # Build Docker image
        docker compose build

        # Start (or restart)
        docker compose up -d

        # Configure Caddy reverse proxy
        if [ -n "$DOMAIN" ]; then
            cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
    reverse_proxy localhost:8000
    header {
        Access-Control-Allow-Origin *
        Access-Control-Allow-Methods "GET, POST, OPTIONS"
        Access-Control-Allow-Headers "*"
    }
}
CADDY
            systemctl reload caddy
            echo "✅ Caddy configured for $DOMAIN (auto-HTTPS)"
        else
            cat > /etc/caddy/Caddyfile <<CADDY
:80 {
    reverse_proxy localhost:8000
    header {
        Access-Control-Allow-Origin *
        Access-Control-Allow-Methods "GET, POST, OPTIONS"
        Access-Control-Allow-Headers "*"
    }
}
CADDY
            systemctl reload caddy
            echo "⚠️  No domain set — running on http://$SERVER_IP"
            echo "   Set DOMAIN in deploy.sh and re-deploy for HTTPS"
        fi

        echo "✅ Deployed! Waiting for health check..."
        sleep 10
        curl -s http://localhost:8000/health | python3 -m json.tool || echo "⏳ Still loading (model takes ~30s)..."
DEPLOY_EOF

    green "Deploy complete!"
    echo ""
    if [ -n "$DOMAIN" ]; then
        echo "🌍 API: https://$DOMAIN"
        echo "📖 Docs: https://$DOMAIN/docs"
    else
        echo "🌍 API: http://$SERVER_IP"
        echo "📖 Docs: http://$SERVER_IP/docs"
    fi
}

cmd_logs() {
    get_ip
    ssh root@"$SERVER_IP" "cd /opt/cardcheck && docker compose logs -f --tail=100"
}

cmd_ssh() {
    get_ip
    ssh root@"$SERVER_IP"
}

cmd_destroy() {
    red "⚠️  This will PERMANENTLY delete the server!"
    read -p "Type server name to confirm ($SERVER_NAME): " confirm
    if [ "$confirm" = "$SERVER_NAME" ]; then
        hcloud server delete "$SERVER_NAME"
        green "Server deleted."
    else
        red "Cancelled."
    fi
}

cmd_status() {
    get_ip
    blue "Server: $SERVER_IP"
    ssh root@"$SERVER_IP" bash <<'EOF'
        echo "── Docker ──"
        docker compose -f /opt/cardcheck/docker-compose.yml ps
        echo ""
        echo "── Health ──"
        curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "❌ API not responding"
        echo ""
        echo "── Resources ──"
        free -h | head -2
        df -h / | tail -1
EOF
}

# ── Main ─────────────────────────────────────────────────────
case "${1:-help}" in
    create)  cmd_create ;;
    setup)   cmd_setup ;;
    deploy)  cmd_deploy ;;
    logs)    cmd_logs ;;
    ssh)     cmd_ssh ;;
    status)  cmd_status ;;
    destroy) cmd_destroy ;;
    *)
        echo "Usage: ./deploy.sh {create|setup|deploy|logs|ssh|status|destroy}"
        echo ""
        echo "  create   — Create Hetzner Cloud server"
        echo "  setup    — Install Docker + Caddy on server"
        echo "  deploy   — Build & deploy the app"
        echo "  logs     — Tail container logs"
        echo "  ssh      — SSH into server"
        echo "  status   — Check server health"
        echo "  destroy  — Delete server (irreversible!)"
        ;;
esac
