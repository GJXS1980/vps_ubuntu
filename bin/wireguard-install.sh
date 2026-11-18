#!/usr/bin/env bash
# Ubuntu 22.04 WireGuard installation and single-peer migration.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo '请使用 sudo/root'; exit 1; }
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 22.04 ]] || { echo '仅支持 Ubuntu 22.04'; exit 1; }
endpoint=${1:-}
count=${2-1}
[[ $# -le 2 && $count =~ ^[1-9][0-9]{0,2}$ ]] && ((count <= 253)) || { echo '初始客户数量须为 1 至 253'; exit 2; }
[[ $endpoint =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || { echo '用法：sudo bash bin/wireguard-install.sh VPS公网IPv4'; exit 2; }
IFS=. read -r -a octets <<< "$endpoint"
for octet in "${octets[@]}"; do
  ((10#$octet <= 255)) || { echo '无效 IPv4'; exit 2; }
done
conf=/etc/wireguard/wgvps.conf
client=/etc/wireguard/windows-vps.conf
sysconf=/etc/sysctl.d/90-ssr-wireguard.conf
backup=/etc/wireguard/wgvps-forwarding-before.txt
src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
manager=/usr/local/sbin/wgvps-users
unit=wgvps-proxy.service
[[ -f $src/wgvps-users.py && -f $src/../systemd/$unit ]] || { echo '请上传整个项目目录'; exit 1; }
umask 077
exec 9>/run/lock/wgvps-install.lock
flock -x 9
install_deps() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y wireguard iptables procps python3 qrencode microsocks
}
finish_install() {
  install -m 0755 "$src/wgvps-users.py" "$manager"
  "$manager" init "$endpoint" --count "$count"
  install -m 0644 "$src/../systemd/$unit" "/etc/systemd/system/$unit"
  systemctl daemon-reload
  systemctl enable --now wg-quick@wgvps
  systemctl enable --now "$unit"
  systemctl is-active --quiet wg-quick@wgvps
  systemctl is-active --quiet "$unit"
  echo '客户管理已就绪。运行 sudo wgvps-users list 查看，云防火墙需放行入站 UDP 51820。'
}
if [[ -f $conf && ( -f $client || -f /etc/wireguard/wgvps-users.json ) ]]; then
  install_deps
  finish_install
  exit 0
fi
for file in "$conf" "$client" "$sysconf" "$backup"; do
  [[ ! -e $file && ! -L $file ]] || { echo "拒绝覆盖：$file"; exit 1; }
done
command -v ip >/dev/null
ip link show wgvps >/dev/null 2>&1 && { echo 'wgvps 接口已存在'; exit 1; }
[[ -z $(ss -H -lun 'sport = :51820') ]] || { echo 'UDP 51820 已占用'; exit 1; }
if ip -4 route show | grep -qE '(^| )10\.66\.77\.'; then
  echo '10.66.77.0/24 与现有路由冲突，请人工选用其他 VPN 网段'; exit 1
fi
wan4=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1);exit}}')
wan6=$(ip -6 route show default | awk '{for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1);exit}}')
wan6=${wan6:-$wan4}
[[ $wan4 =~ ^[A-Za-z0-9_.:-]+$ && $wan6 =~ ^[A-Za-z0-9_.:-]+$ ]] || { echo '无法确定出口网卡'; exit 1; }
install_deps
modprobe wireguard
# Fail before writing keys if this host cannot handle our IPv6 policy.
ip6tables -w -t nat -L POSTROUTING -n >/dev/null
umask 077
install -d -m 0700 /etc/wireguard
server_key=$(wg genkey)
server_pub=$(printf '%s\n' "$server_key" | wg pubkey)
client_key=$(wg genkey)
client_pub=$(printf '%s\n' "$client_key" | wg pubkey)
psk=$(wg genpsk)
sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding "net.ipv6.conf.$wan6.accept_ra" > "$backup"
cat > "$sysconf" <<EOF
net.ipv4.ip_forward = 1
net.ipv6.conf.$wan6.accept_ra = 2
net.ipv6.conf.all.forwarding = 1
EOF
sysctl -p "$sysconf"
cat > "$conf" <<EOF
[Interface]
Address = 10.66.77.1/24, fd42:66:77::1/64
ListenPort = 51820
PrivateKey = $server_key
MTU = 1380
PostUp = iptables -w -I INPUT 1 -p udp --dport 51820 -m comment --comment wgvps -j ACCEPT
PostUp = iptables -w -I FORWARD 1 -i %i -o $wan4 -s 10.66.77.0/24 -m comment --comment wgvps -j ACCEPT
PostUp = iptables -w -I FORWARD 1 -i $wan4 -o %i -d 10.66.77.0/24 -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment wgvps -j ACCEPT
PostUp = iptables -w -t nat -A POSTROUTING -s 10.66.77.0/24 -o $wan4 -m comment --comment wgvps -j MASQUERADE
PostUp = ip6tables -w -I FORWARD 1 -i %i -o $wan6 -s fd42:66:77::/64 -m comment --comment wgvps -j ACCEPT
PostUp = ip6tables -w -I FORWARD 1 -i $wan6 -o %i -d fd42:66:77::/64 -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment wgvps -j ACCEPT
PostUp = ip6tables -w -t nat -A POSTROUTING -s fd42:66:77::/64 -o $wan6 -m comment --comment wgvps -j MASQUERADE
PostDown = iptables -w -D INPUT -p udp --dport 51820 -m comment --comment wgvps -j ACCEPT
PostDown = iptables -w -D FORWARD -i %i -o $wan4 -s 10.66.77.0/24 -m comment --comment wgvps -j ACCEPT
PostDown = iptables -w -D FORWARD -i $wan4 -o %i -d 10.66.77.0/24 -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment wgvps -j ACCEPT
PostDown = iptables -w -t nat -D POSTROUTING -s 10.66.77.0/24 -o $wan4 -m comment --comment wgvps -j MASQUERADE
PostDown = ip6tables -w -D FORWARD -i %i -o $wan6 -s fd42:66:77::/64 -m comment --comment wgvps -j ACCEPT
PostDown = ip6tables -w -D FORWARD -i $wan6 -o %i -d fd42:66:77::/64 -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment wgvps -j ACCEPT
PostDown = ip6tables -w -t nat -D POSTROUTING -s fd42:66:77::/64 -o $wan6 -m comment --comment wgvps -j MASQUERADE

[Peer]
PublicKey = $client_pub
PresharedKey = $psk
AllowedIPs = 10.66.77.2/32, fd42:66:77::2/128
EOF
cat > "$client" <<EOF
[Interface]
PrivateKey = $client_key
Address = 10.66.77.2/32, fd42:66:77::2/128
DNS = 1.1.1.1, 1.0.0.1
MTU = 1380

[Peer]
PublicKey = $server_pub
PresharedKey = $psk
Endpoint = $endpoint:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
EOF
chmod 0600 "$conf" "$client" "$backup"
unset server_key client_key psk
finish_install
