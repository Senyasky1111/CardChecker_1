#!/bin/bash
# Decrypt + extract v3 dataset, then bootstrap pod (backbone test + SAM2 install).
# Avoids the chat-paste space-eating issue with openssl -pass arg.
#
# Prereq:  export DECRYPT_PASS='<passphrase>'
# Run:     curl -sL <this script url> | bash

set -eu

test -n "${DECRYPT_PASS:-}" || { echo "ERROR: Set DECRYPT_PASS env var first"; exit 1; }
test "${#DECRYPT_PASS}" -eq 44 || echo "WARN: DECRYPT_PASS length is ${#DECRYPT_PASS} (expected 44)"

cd /workspace

if [ ! -f /workspace/_v3_archive.tar.gz.enc ]; then
    echo "ERROR: /workspace/_v3_archive.tar.gz.enc missing — re-run download first"
    exit 1
fi

echo "=== [1/4] Decrypting (10-15 min on 35 GB AES-256-CBC)... ==="
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
    -in /workspace/_v3_archive.tar.gz.enc \
    -out /workspace/_v3_archive.tar.gz \
    -pass env:DECRYPT_PASS

echo "=== [2/4] Extracting (3-5 min)... ==="
mkdir -p /workspace/data
tar -xzf /workspace/_v3_archive.tar.gz -C /workspace/data
rm -f /workspace/_v3_archive.tar.gz.enc /workspace/_v3_archive.tar.gz
du -sh /workspace/data/tag_v3

echo "=== [3/4] Cloning CardChecker... ==="
if [ -d /workspace/CardChecker ]; then
    cd /workspace/CardChecker && git pull
else
    git clone https://github.com/Senyasky1111/CardChecker_1.git /workspace/CardChecker
fi

echo "=== [4/4] Running bootstrap (backbone test + SAM2 install)... ==="
bash /workspace/CardChecker/scripts/runpod/bootstrap_pod.sh
