#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo '请使用 sudo/root'; exit 1; }
. /etc/os-release
[[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 22.04 ]] || { echo '仅支持 Ubuntu 22.04'; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/ssr-admin
[[ ! -e "$APP" && ! -e /etc/systemd/system/ssr-admin.service && ! -e /etc/systemd/system/ssr-admin-firewall.service ]] || { echo '管理器已存在；请备份后按文档更新，拒绝覆盖'; exit 1; }
[[ -f /etc/ssr/config.json && -f /opt/ssr/shadowsocks/server.py ]] || { echo '请先安装 SSR'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 qrencode iptables iproute2 kmod openssl procps
install -d -m 0755 "$APP/bin" "$APP/templates"
for f in ssr-admin.py ssr_backend.py ssr_system.py ssr_admin_compat.py; do
  install -m 0644 "$ROOT/bin/$f" "$APP/bin/$f"
done
install -m 0644 "$ROOT/templates/admin.html" "$APP/templates/admin.html"
install -d -m 0700 /etc/ssr-admin
if [[ ! -e /etc/ssr-admin/admin.env ]]; then
  umask 077
  printf 'SSR_ADMIN_TOKEN=%s\n' "$(openssl rand -hex 32)" > /etc/ssr-admin/admin.env
fi
python3 "$APP/bin/ssr-admin.py" backend-patch
install -m 0644 "$ROOT/systemd/ssr-admin.service" /etc/systemd/system/ssr-admin.service
install -m 0644 "$ROOT/systemd/ssr-admin-firewall.service" /etc/systemd/system/ssr-admin-firewall.service
systemd-analyze verify /etc/systemd/system/ssr-admin.service /etc/systemd/system/ssr-admin-firewall.service
systemctl daemon-reload
systemctl enable --now ssr-admin-firewall.service ssr-admin.service
systemctl is-active --quiet ssr-admin.service
echo '管理器已安装。令牌：sudo cat /etc/ssr-admin/admin.env'
echo '本地运行 ssh -L 9080:127.0.0.1:9080 ubuntu@服务器，然后浏览器打开 http://127.0.0.1:9080'
echo '适配补丁需重启 SSR 生效：sudo systemctl restart ssr'
