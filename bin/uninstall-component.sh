#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "请使用 sudo/root"; exit 1; }
case "${1:-}" in
 ssr) SVC=ssr; APP=/opt/ssr; CONF=/etc/ssr; USER=ssr;;
 rust) SVC=shadowsocks-rust; APP=/opt/shadowsocks-rust; CONF=/etc/shadowsocks-rust; USER=ssrust;;
 *) echo "参数必须是 ssr 或 rust"; exit 2;;
esac
read -r -p "确认卸载 $SVC？配置将备份后移除 [y/N]: " a
[[ "$a" == y || "$a" == Y ]] || exit 0
systemctl disable --now "$SVC" 2>/dev/null || true
rm -f "/etc/systemd/system/$SVC.service"
systemctl daemon-reload
if [[ -d "$CONF" ]]; then cp -a "$CONF" "${CONF}.backup.$(date +%Y%m%d%H%M%S)"; rm -rf "$CONF"; fi
rm -rf "$APP"
id "$USER" >/dev/null 2>&1 && userdel "$USER" || true
echo "$SVC 已卸载；配置备份目录已保留。"
