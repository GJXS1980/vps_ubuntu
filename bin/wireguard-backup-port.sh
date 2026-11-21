#!/usr/bin/env bash
# Optional second IPv4 UDP entry point for the existing wgvps interface.
set -Eeuo pipefail
unit=wgvps-backup-port.service
state=/run/wgvps-backup-port/wan
rule() {
  iptables -w -t nat "$1" PREROUTING -i "$wan" -m addrtype --dst-type LOCAL \
    -p udp --dport 51821 -m comment --comment wgvps-backup -j REDIRECT --to-ports 51820
}
case ${1:-install} in
  install)
    install -D -m 0755 "$0" /usr/local/libexec/wgvps-backup-port
    cat > "/etc/systemd/system/$unit" <<'EOF'
[Unit]
Description=Secondary UDP port for wgvps
Requires=wg-quick@wgvps.service
After=wg-quick@wgvps.service
PartOf=wg-quick@wgvps.service

[Service]
Type=oneshot
RemainAfterExit=yes
RuntimeDirectory=wgvps-backup-port
ExecStart=/usr/local/libexec/wgvps-backup-port start
ExecStop=/usr/local/libexec/wgvps-backup-port stop

[Install]
WantedBy=wg-quick@wgvps.service
EOF
    systemctl daemon-reload
    systemctl enable --now "$unit"
    ;;
  start)
    [[ $(wg show wgvps listen-port) == 51820 ]]
    if [[ -n $(ss -H -lun 'sport = :51821') ]]; then
      echo 'UDP 51821 已被占用' >&2
      exit 1
    fi
    wan=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1);exit}}')
    [[ -n $wan ]]
    printf '%s\n' "$wan" > "$state"
    rule -C 2>/dev/null || rule -A
    ;;
  stop)
    read -r wan < "$state"
    rule -D
    ;;
  *) exit 2 ;;
esac
