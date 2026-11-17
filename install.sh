#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "请使用 sudo/root"; exit 1; }
. /etc/os-release
[[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 22.04 ]] || { echo "仅支持 Ubuntu 22.04"; exit 1; }
echo "Ubuntu 22.04 双版本部署"
echo "1) SSR 兼容服务"
echo "2) Shadowsocks-Rust 现代 SS 服务"
echo "3) 两者都安装"
echo "4) 环境检查"
read -r -p "请选择 [1-4]: " choice
case "$choice" in
  1) exec "$ROOT/bin/ssr-install.sh" ;;
  2) exec "$ROOT/bin/rust-install.sh" ;;
  3) "$ROOT/bin/ssr-install.sh"; "$ROOT/bin/rust-install.sh" ;;
  4) exec "$ROOT/manage.sh" check ;;
  *) echo "已取消"; exit 0 ;;
esac
