#!/usr/bin/env bash
set -euo pipefail
umask 077
dir=$(mktemp -d /root/wg-portal-upgrade.XXXXXX)
cp -a /etc/wg-portal /usr/local/lib/wg-portal/api.py /usr/local/lib/wg-portal/manager.py /usr/local/sbin/wg-portal-bridge /etc/systemd/system/wg-portal-agent.service "$dir"
bash "$(dirname "$0")/wireguard-portal-agent-install.sh"
