#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]]
systemctl disable --now wg-portal-agent
rm -f /etc/systemd/system/wg-portal-agent.service /etc/sudoers.d/wg-portal /usr/local/sbin/wg-portal-bridge
systemctl daemon-reload
echo '已移除 Agent 服务及 sudo 授权。证书、隧道与 Peer 保留。'
