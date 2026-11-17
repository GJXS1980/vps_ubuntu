#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "请使用 sudo/root"; exit 1; }
. /etc/os-release
[[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 22.04 ]] || { echo "仅支持 Ubuntu 22.04"; exit 1; }
APP=/opt/ssr; CONF_DIR=/etc/ssr; CONF=$CONF_DIR/config.json
UNIT=/etc/systemd/system/ssr.service
REPO="${SSR_REPO:-https://github.com/shadowsocksrr/shadowsocksr.git}"
BRANCH="${SSR_BRANCH:-manyuser}"
[[ ! -e "$APP" && ! -e "$CONF_DIR" && ! -e "$UNIT" ]] || { echo "检测到现有 SSR 文件/服务，拒绝覆盖。请先备份并人工处理。"; exit 1; }
read -r -p "SSR 监听端口 [8388]: " PORT; PORT=${PORT:-8388}
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT>0 && PORT<65536)) || { echo "端口无效"; exit 1; }
read -r -s -p "SSR 密码（留空自动生成）: " PASSWORD; echo
PASSWORD=${PASSWORD:-$(openssl rand -hex 24)}
read -r -p "加密方式 [aes-256-cfb]: " METHOD; METHOD=${METHOD:-aes-256-cfb}
read -r -p "协议 [auth_sha1_v4]: " PROTOCOL; PROTOCOL=${PROTOCOL:-auth_sha1_v4}
read -r -p "混淆 [tls1.2_ticket_auth]: " OBFS; OBFS=${OBFS:-tls1.2_ticket_auth}
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git ca-certificates python3 python3-venv python3-pip python3-dev build-essential libssl-dev libffi-dev libsodium-dev openssl
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
git clone --depth 1 --branch "$BRANCH" "$REPO" "$TMP/source"
[[ -f "$TMP/source/shadowsocks/server.py" ]] || { echo "仓库中未找到 shadowsocks/server.py"; exit 1; }
# 不擅自叠加未经核实的 Python 兼容补丁；先做 Python 3 语法预检。
python3 -m compileall -q "$TMP/source/shadowsocks" || {
  echo "该 SSR 分支不能通过当前 Python 3 语法预检。安装已中止；请指定已验证的 Python 3 SSR fork/补丁集。"
  exit 1
}
install -d -m 0755 "$APP" "$CONF_DIR"
cp -a "$TMP/source/shadowsocks" "$APP/"
python3 -m venv "$APP/venv"
if [[ -f "$TMP/source/requirements.txt" ]]; then "$APP/venv/bin/pip" install -r "$TMP/source/requirements.txt"; fi
if [[ -f "$TMP/source/requestment.txt" ]]; then "$APP/venv/bin/pip" install -r "$TMP/source/requestment.txt"; fi
if [[ -f "$TMP/source/setup.py" ]]; then "$APP/venv/bin/pip" install "$TMP/source"; fi
export PORT PASSWORD METHOD PROTOCOL OBFS
python3 - <<'PY'
import json, os
c={"server":"0.0.0.0","server_ipv6":"::","server_port":int(os.environ["PORT"]),
"local_address":"127.0.0.1","local_port":1080,"password":os.environ["PASSWORD"],
"method":os.environ["METHOD"],"protocol":os.environ["PROTOCOL"],"protocol_param":"",
"obfs":os.environ["OBFS"],"obfs_param":"","speed_limit_per_con":0,"speed_limit_per_user":0,
"additional_ports":{},"timeout":120,"udp_timeout":60,"dns_ipv6":False,
"connect_verbose_info":0,"redirect":"","fast_open":False}
with open("/etc/ssr/config.json","w") as f: json.dump(c,f,indent=2)
os.chmod("/etc/ssr/config.json",0o640)
PY
id ssr >/dev/null 2>&1 || useradd --system --home /opt/ssr --shell /usr/sbin/nologin ssr
chown -R root:root "$APP"; chmod -R go-w "$APP"
chown root:ssr "$CONF"; chmod 0640 "$CONF"
cat > "$UNIT" <<EOF
[Unit]
Description=ShadowsocksR compatibility server
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=ssr
Group=ssr
WorkingDirectory=$APP/shadowsocks
ExecStart=$APP/venv/bin/python $APP/shadowsocks/server.py -c $CONF
Restart=on-failure
RestartSec=3
LimitNOFILE=65535
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
[Install]
WantedBy=multi-user.target
EOF
systemd-analyze verify "$UNIT"
systemctl daemon-reload
systemctl enable --now ssr
sleep 2
systemctl is-active --quiet ssr || { journalctl -u ssr -n 80 --no-pager; exit 1; }
echo "SSR 服务已启动。端口=$PORT 密码=$PASSWORD"
echo "注意：语法检查和服务启动不代表每种 SSR 客户端/协议组合均已互通，请执行验收测试。"
