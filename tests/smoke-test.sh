#!/usr/bin/env bash
set -u
fail=0
check(){ if eval "$2"; then printf '[PASS] %s\n' "$1"; else printf '[FAIL] %s\n' "$1"; fail=1; fi; }
check "systemd 可用" 'command -v systemctl >/dev/null'
check "SSR 配置 JSON（若已安装）" '[[ ! -f /etc/ssr/config.json ]] || python3 -m json.tool /etc/ssr/config.json >/dev/null'
check "Rust 配置 JSON（若已安装）" '[[ ! -f /etc/shadowsocks-rust/config.json ]] || python3 -m json.tool /etc/shadowsocks-rust/config.json >/dev/null'
check "SSR unit 校验（若已安装）" '[[ ! -f /etc/systemd/system/ssr.service ]] || systemd-analyze verify /etc/systemd/system/ssr.service'
check "Rust unit 校验（若已安装）" '[[ ! -f /etc/systemd/system/shadowsocks-rust.service ]] || systemd-analyze verify /etc/systemd/system/shadowsocks-rust.service'
check "SSR 服务状态（若已安装）" '[[ ! -f /etc/systemd/system/ssr.service ]] || systemctl is-active --quiet ssr'
check "Rust 服务状态（若已安装）" '[[ ! -f /etc/systemd/system/shadowsocks-rust.service ]] || systemctl is-active --quiet shadowsocks-rust'
if [[ -f /etc/ssr/config.json ]]; then
 p=$(python3 -c 'import json;print(json.load(open("/etc/ssr/config.json"))["server_port"])')
 check "SSR TCP 监听 $p" "ss -lnt | grep -q ':$p '"
fi
if [[ -f /etc/shadowsocks-rust/config.json ]]; then
 p=$(python3 -c 'import json;print(json.load(open("/etc/shadowsocks-rust/config.json"))["server_port"])')
 check "Rust TCP 监听 $p" "ss -lnt | grep -q ':$p '"
fi
exit "$fail"
