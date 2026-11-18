#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $EUID == 0 ]]
repo=$(cd "$(dirname "$0")/../../.." && pwd)
cfg=/etc/wg-portal
app=/usr/local/lib/wg-portal
test -s /etc/wireguard/wgvps-users.json
for f in network client-ca.crt server.crt server.key; do test -s "$cfg/$f"; done
test -s /etc/wireguard/wgportal.conf
apt-get update
apt-get install -y python3-venv sudo
getent group wg-portal >/dev/null || groupadd --system wg-portal
getent passwd wg-portal >/dev/null || useradd --gid wg-portal --system --no-create-home --shell /usr/sbin/nologin wg-portal
install -d -m 0755 "$app"
chown root:wg-portal "$cfg" "$cfg/server.key"
chmod 0750 "$cfg"
chmod 0640 "$cfg/server.key"
chmod 0644 "$cfg/server.crt" "$cfg/client-ca.crt"
install -m 0644 "$repo/bin/wgvps-users.py" "$app/manager.py"
install -m 0644 "$repo/wireguard-portal/agent/api.py" "$app/api.py"
install -m 0755 "$repo/wireguard-portal/agent/bridge.py" /usr/local/sbin/wg-portal-bridge
(
umask 022
python3 -m venv "$app/venv"
"$app/venv/bin/pip" install 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1' 'pydantic>=2,<3'
)
runuser -u wg-portal -- "$app/venv/bin/python" -c "import fastapi,uvicorn"
stage=$(mktemp)
trap 'rm -f -- "$stage"' EXIT
echo 'wg-portal ALL=(root) NOPASSWD: /usr/local/sbin/wg-portal-bridge ""' > "$stage"
visudo -cf "$stage"
install -m 0440 "$stage" /etc/sudoers.d/wg-portal
install -m 0644 "$repo/wireguard-portal/agent/systemd/wg-portal-agent.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable wg-portal-agent
systemctl restart wg-portal-agent
systemctl is-active --quiet wg-portal-agent
