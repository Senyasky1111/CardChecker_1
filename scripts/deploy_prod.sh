#!/usr/bin/env bash
# Robust prod deploy for the FastAPI backend (Hetzner Docker at /opt/cardcheck).
#
# Why this exists: a plain `ssh root@host 'docker compose build'` gets KILLED when the SSH
# session drops mid-build (the heavy torch/anthropic install briefly stalls the box). This
# script runs the build DETACHED on the server (nohup) so it survives the drop, captures a
# rollback image tag first, then polls + smoke-tests.
#
# Ships ONLY code (src/ + requirements + Dockerfile + compose) — NEVER data/cards.db or .env
# (those live on the server and must not be clobbered). Read vault/.../deploy-safety-rules.md.
#
# Usage:  ./scripts/deploy_prod.sh            # build + deploy + smoke
#         ./scripts/deploy_prod.sh --rollback # revert to the cardcheck-api:rollback image
set -euo pipefail

HOST="${CC_DEPLOY_HOST:-root@89.167.31.124}"
DIR="/opt/cardcheck"
LOG="/tmp/cc_deploy.log"
SSH="ssh -o BatchMode=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=10"

if [[ "${1:-}" == "--rollback" ]]; then
  echo ">> ROLLBACK to cardcheck-api:rollback"
  $SSH "$HOST" "cd $DIR && docker tag cardcheck-api:rollback cardcheck-api:latest && docker compose up -d && echo ROLLED_BACK"
  exit 0
fi

cd "$(dirname "$0")/.."   # repo root

echo ">> [1/5] Pre-flight: tests must be green"
./venv/Scripts/python.exe -m pytest tests/test_pregrade_distribution.py tests/test_pregrade_service.py \
  tests/test_grade_gate.py tests/test_grade_endpoint.py -q || { echo "TESTS FAILED — aborting"; exit 1; }

echo ">> [2/5] Tar code (src + requirements + Dockerfile + compose only — no data/.env)"
tar czf /tmp/cc_deploy.tar.gz --exclude='__pycache__' --exclude='*.pyc' \
  src/ requirements.txt Dockerfile docker-compose.yml
scp -o BatchMode=yes /tmp/cc_deploy.tar.gz "$HOST:/tmp/"

echo ">> [3/5] Extract + snapshot rollback tag + start DETACHED build"
$SSH "$HOST" "cd $DIR && \
  tar xzf /tmp/cc_deploy.tar.gz && \
  IMG=\$(docker compose images -q api 2>/dev/null | head -1) && \
  [ -n \"\$IMG\" ] && docker tag \$IMG cardcheck-api:rollback && echo \"rollback tag -> \$IMG\" ; \
  rm -f $LOG && \
  nohup bash -c 'docker compose build api && docker compose up -d && echo BUILD_OK || echo BUILD_FAIL' > $LOG 2>&1 & \
  echo started"

echo ">> [4/5] Poll detached build (survives SSH drops; retries on reset)"
for attempt in $(seq 1 40); do
  RES=$($SSH "$HOST" "grep -oE 'BUILD_OK|BUILD_FAIL' $LOG 2>/dev/null | tail -1" 2>/dev/null || true)
  [[ "$RES" == "BUILD_OK" ]] && { echo "build OK"; break; }
  [[ "$RES" == "BUILD_FAIL" ]] && { echo "BUILD FAILED — see $HOST:$LOG"; exit 1; }
  sleep 15
done

echo ">> [5/5] Smoke test"
$SSH "$HOST" "cd $DIR && \
  for i in 1 2 3 4 5 6 7 8; do c=\$(curl -s -m 8 http://localhost:8000/health -o /dev/null -w '%{http_code}'); \
    [ \"\$c\" = 200 ] && break || sleep 6; done; \
  echo health=\$c; \
  docker compose logs api --tail=40 2>/dev/null | grep -iE 'grader ready|error|traceback' | tail -3"

echo ">> DONE. If broken: ./scripts/deploy_prod.sh --rollback"
