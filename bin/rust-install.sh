#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "请使用 sudo/root"; exit 1; }
. /etc/os-release
[[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 22.04 ]] || { echo "仅支持 Ubuntu 22.04"; exit 1; }
APP=/opt/shadowsocks-rust; CONF_DIR=/etc/shadowsocks-rust; CONF=$CONF_DIR/config.json
UNIT=/etc/systemd/system/shadowsocks-rust.service
VERSION="${SS_RUST_VERSION:-v1.25.0}"
[[ ! -e "$APP" && ! -e "$CONF_DIR" && ! -e "$UNIT" ]] || { echo "检测到现有 Rust SS 文件/服务，拒绝覆盖。"; exit 1; }
ARCH=$(uname -m)
case "$ARCH" in x86_64) TARGET=x86_64-unknown-linux-gnu ;; aarch64|arm64) TARGET=aarch64-unknown-linux-gnu ;; *) echo "暂不支持架构: $ARCH"; exit 1 ;; esac
read -r -p "SS 监听端口 [8389]: " PORT; PORT=${PORT:-8389}
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT>0 && PORT<65536)) || { echo "端口无效"; exit 1; }
read -r -s -p "SS 密码（留空自动生成）: " PASSWORD; echo
PASSWORD=${PASSWORD:-$(openssl rand -base64 32 | tr -d '\n')}
read -r -p "加密方式 [aes-256-gcm]: " METHOD; METHOD=${METHOD:-aes-256-gcm}
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y curl ca-certificates python3 xz-utils openssl
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
API="https://api.github.com/repos/shadowsocks/shadowsocks-rust/releases/tags/$VERSION"
python3 - "$API" "$TARGET" "$TMP/assets.json" <<'PY'
import json,sys,urllib.request
req=urllib.request.Request(sys.argv[1],headers={"Accept":"application/vnd.github+json","User-Agent":"ssr-ubuntu2204-dual-installer"})
with urllib.request.urlopen(req,timeout=30) as r: data=json.load(r)
target=sys.argv[2]
assets=data.get("assets",[])
archive=next((a for a in assets if a["name"].endswith(target+".tar.xz") and a["name"].startswith("shadowsocks-"+data["tag_name"])),None)
if not archive: raise SystemExit("官方 Release 中没有找到目标架构压缩包")
checksum=next((a for a in assets if a["name"]==archive["name"]+".sha256"),None)
if not checksum: raise SystemExit("官方 SHA256 sidecar 不存在，拒绝无校验安装")
with open(sys.argv[3],"w") as f: json.dump({"archive":archive["browser_download_url"],"checksum":checksum["browser_download_url"],"name":archive["name"]},f)
PY
readarray -t URLS < <(python3 - "$TMP/assets.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1])); print(d["archive"]); print(d["checksum"]); print(d["name"])
PY
)
curl -fL --retry 3 "${URLS[0]}" -o "$TMP/ss.tar.xz"
curl -fL --retry 3 "${URLS[1]}" -o "$TMP/ss.tar.xz.sha256"
EXPECTED=$(awk '{print $1}' "$TMP/ss.tar.xz.sha256")
ACTUAL=$(sha256sum "$TMP/ss.tar.xz" | awk '{print $1}')
[[ "$EXPECTED" == "$ACTUAL" ]] || { echo "SHA256 校验失败"; exit 1; }
mkdir -p "$TMP/unpack"; tar -xJf "$TMP/ss.tar.xz" -C "$TMP/unpack"
SSSERVER=$(find "$TMP/unpack" -type f -name ssserver -perm -u+x | head -n1)
[[ -n "$SSSERVER" ]] || { echo "发布包中没有 ssserver"; exit 1; }
install -d -m 0755 "$APP" "$CONF_DIR"
install -m 0755 "$SSSERVER" "$APP/ssserver"
export PORT PASSWORD METHOD
python3 - <<'PY'
import json,os
c={"server":"0.0.0.0","server_port":int(os.environ["PORT"]),
"password":os.environ["PASSWORD"],"method":os.environ["METHOD"],"mode":"tcp_and_udp"}
with open("/etc/shadowsocks-rust/config.json","w") as f: json.dump(c,f,indent=2)
os.chmod("/etc/shadowsocks-rust/config.json",0o640)
PY
id ssrust >/dev/null 2>&1 || useradd --system --home /opt/shadowsocks-rust --shell /usr/sbin/nologin ssrust
chown -R root:root "$APP"; chmod -R go-w "$APP"
chown root:ssrust "$CONF"; chmod 0640 "$CONF"
"$APP/ssserver" --version
cat > "$UNIT" <<EOF
[Unit]
Description=Shadowsocks Rust server
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=ssrust
Group=ssrust
ExecStart=$APP/ssserver -c $CONF
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
systemctl enable --now shadowsocks-rust
sleep 2
systemctl is-active --quiet shadowsocks-rust || { journalctl -u shadowsocks-rust -n 80 --no-pager; exit 1; }
echo "Rust SS 服务已启动。版本=$VERSION 端口=$PORT 密码=$PASSWORD"
