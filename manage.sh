#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
action="${1:-status}"
component="${2:-all}"
svc_for(){ case "$1" in ssr) echo ssr;; rust) echo shadowsocks-rust;; *) return 1;; esac; }
if [[ "$action" == check ]]; then exec bash "$ROOT/tests/smoke-test.sh"; fi
if [[ "$action" == status ]]; then
  for s in ssr shadowsocks-rust; do
    if systemctl list-unit-files "$s.service" --no-legend 2>/dev/null | grep -q "$s.service"; then
      systemctl --no-pager --full status "$s" || true
    else echo "$s: 未安装"; fi
  done
  exit 0
fi
if [[ "$action" == uninstall ]]; then
  [[ $EUID -eq 0 ]] || { echo "请使用 sudo/root"; exit 1; }
  case "${2:-}" in ssr|rust) exec bash "$ROOT/bin/uninstall-component.sh" "$2";; *) echo "用法: sudo ./manage.sh uninstall {ssr|rust}"; exit 2;; esac
fi
[[ "$component" == ssr || "$component" == rust ]] || { echo "用法: $0 {status|check|uninstall} 或 $0 {start|stop|restart|logs} {ssr|rust}"; exit 2; }
svc=$(svc_for "$component")
case "$action" in
 start) systemctl start "$svc";;
 stop) systemctl stop "$svc";;
 restart) systemctl restart "$svc";;
 logs) journalctl -u "$svc" -f;;
 *) echo "未知操作"; exit 2;;
esac
