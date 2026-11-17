#!/usr/bin/env bash
set -Eeuo pipefail
echo "更新请先在测试机验证。当前安装器通过 SS_RUST_VERSION 固定版本重新部署；不要在生产运行中覆盖二进制。"
echo "请备份 /etc/shadowsocks-rust/config.json，下载并校验新版本后，在维护窗口替换 /opt/shadowsocks-rust/ssserver 并重启服务。"
exit 2
