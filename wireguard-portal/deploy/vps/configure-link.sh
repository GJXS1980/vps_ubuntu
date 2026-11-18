#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $EUID == 0 ]]
src=${1:?传入已安全上传的 vps 目录}
for file in server.key server.crt client-ca.crt wgportal.conf network; do
  [[ -f "$src/$file" && ! -L "$src/$file" ]]
done
for pair in "wgportal.conf:/etc/wireguard/wgportal.conf" "network:/etc/wg-portal/network" "server.key:/etc/wg-portal/server.key" "client-ca.crt:/etc/wg-portal/client-ca.crt" "server.crt:/etc/wg-portal/server.crt"; do
  dest=${pair#*:}; source_file="$src/${pair%%:*}"
  if [[ -e "$dest" ]] && ! cmp -s "$source_file" "$dest"; then echo "拒绝覆盖 $dest"; exit 1; fi
done
port=$(awk '/^ListenPort = / {print $3}' "$src/wgportal.conf")
[[ "$port" =~ ^[0-9]+$ && "$port" != 51820 ]]
if ! ip link show wgportal >/dev/null 2>&1; then
  [[ -z $(ss -H -lun "sport = :$port") ]] || { echo '管理 UDP 端口已被占用'; exit 1; }
fi
echo '请确认管理 /30 与双方现有路由无冲突，且已批准使用新的独立 WireGuard 接口。'
read -rp '输入 APPLY 启动专用管理隧道: ' confirm
[[ "$confirm" == APPLY ]]
install -d -m 0700 /etc/wg-portal
for file in network server.key server.crt client-ca.crt; do
  [[ -e "/etc/wg-portal/$file" ]] || install -m 0600 "$src/$file" "/etc/wg-portal/$file"
done
[[ -e /etc/wireguard/wgportal.conf ]] || install -m 0600 "$src/wgportal.conf" /etc/wireguard/wgportal.conf
systemctl enable --now wg-quick@wgportal

