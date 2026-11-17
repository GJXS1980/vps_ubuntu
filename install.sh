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
echo "5) 安装 Web 与终端账号管理器（先安装 SSR）"
read -r -p "请选择 [1-5]: " choice
case "$choice" in
  1) exec bash "$ROOT/bin/ssr-install.sh" ;;
  2) exec bash "$ROOT/bin/rust-install.sh" ;;
  3) bash "$ROOT/bin/ssr-install.sh"; bash "$ROOT/bin/rust-install.sh" ;;
  4) exec bash "$ROOT/manage.sh" check ;;
  5) exec bash "$ROOT/bin/admin-install.sh" ;;
  *) echo "已取消"; exit 0 ;;
esac
