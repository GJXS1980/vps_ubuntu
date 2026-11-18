#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID == 0 ]] || { echo '请使用 sudo/root'; exit 1; }
src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
address=${1:-}
[[ -f /etc/wireguard/wgvps-users.json ]] || { echo '请先安装 WireGuard 用户管理器'; exit 1; }
network=$(python3 - "$address" <<'PY'
import ipaddress, json, subprocess, sys
ip = ipaddress.IPv4Address(sys.argv[1])
private = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
if not any(ip in ipaddress.ip_network(n) for n in private):
    sys.exit("请输入 VPS 网卡上的内网 IPv4")
for link in json.loads(subprocess.check_output(["ip", "-j", "-4", "addr", "show"])):
    for addr in link["addr_info"]:
        if addr["local"] == str(ip):
            network = ipaddress.ip_network((ip, addr["prefixlen"]), strict=False)
            if not any(network.subnet_of(ipaddress.ip_network(n)) for n in private):
                sys.exit("网卡前缀超出内网范围")
            print(network)
            sys.exit()
sys.exit("该地址不属于本机网卡")
PY
)
exec 9>/run/lock/wgvps-web-install.lock
flock -x 9
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y gunicorn sudo qrencode openssl
cfg=/etc/wgvps-web
app=/usr/local/lib/wgvps-web
install -d -m 0700 "$cfg"
install -d -m 0755 "$app"
getent passwd wgvps-web >/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin wgvps-web
stage=$(mktemp -d "$cfg/setup.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
if [[ ! -s $cfg/password ]]; then
  openssl rand -hex 24 > "$stage/password"
  install -m 0600 "$stage/password" "$cfg/password"
fi
if [[ ! -f $cfg/ca.key || ! -f $cfg/ca.crt ]]; then
  [[ ! -e $cfg/ca.key && ! -e $cfg/ca.crt ]] || { echo '内网 CA 文件不完整'; exit 1; }
  openssl req -x509 -newkey rsa:3072 -nodes -days 3650 -subj '/CN=WireGuard local portal CA' \
    -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' -addext 'keyUsage=critical,keyCertSign,cRLSign' \
    -keyout "$stage/ca.key" -out "$stage/ca.crt"
  install -m 0600 "$stage/ca.key" "$cfg/ca.key"
  install -m 0644 "$stage/ca.crt" "$cfg/ca.crt"
fi
openssl req -new -newkey rsa:2048 -nodes -subj "/CN=$address" -keyout "$stage/tls.key" -out "$stage/tls.csr"
cat > "$stage/extensions" <<EOF
subjectAltName=IP:$address
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
EOF
openssl x509 -req -in "$stage/tls.csr" -CA "$cfg/ca.crt" -CAkey "$cfg/ca.key" -CAcreateserial \
  -days 365 -extfile "$stage/extensions" -out "$stage/tls.crt"
cat > "$stage/sudoers" <<'EOF'
wgvps-web ALL=(root) NOPASSWD: /usr/local/sbin/wgvps-users list, /usr/local/sbin/wgvps-users redeem, /usr/local/sbin/wgvps-users issue user??, /usr/local/sbin/wgvps-users enable user??, /usr/local/sbin/wgvps-users disable user??
EOF
visudo -cf "$stage/sudoers"
install -m 0440 "$stage/sudoers" /etc/sudoers.d/wgvps-web
install -m 0755 "$src/wgvps-users.py" /usr/local/sbin/wgvps-users
install -m 0644 "$src/wgvps_web.py" "$app/wgvps_web.py"
install -m 0600 "$stage/tls.key" "$cfg/tls.key"
install -m 0644 "$stage/tls.crt" "$cfg/tls.crt"
printf 'WEB_ADDRESS=%s\nWEB_NETWORK=%s\n' "$address" "$network" > "$cfg/network"
install -m 0644 "$src/../systemd/wgvps-web.service" /etc/systemd/system/wgvps-web.service
systemctl daemon-reload
systemctl enable wgvps-web.service
systemctl restart wgvps-web.service
for i in {1..15}; do
  if python3 - "$address" "$cfg/ca.crt" <<'PY'
import http.client, ssl, sys
c = http.client.HTTPSConnection(sys.argv[1], 8443, timeout=2, context=ssl.create_default_context(cafile=sys.argv[2]))
try:
    c.request("GET", "/")
    sys.exit(0 if c.getresponse().status == 200 else 1)
except OSError:
    sys.exit(1)
PY
  then
    echo "管理页 https://$address:8443/admin  用户 admin；用 sudo cat $cfg/password 查看密码"
    echo "向设备提供受信任的 $cfg/ca.crt；领取设备须能访问 $network。"
    exit 0
  fi
  sleep 1
done
echo 'HTTPS 检查失败，请查看 journalctl -u wgvps-web'
exit 1
