# 部署实施手册

## A. 上线前准备

1. 确认 Ubuntu 22.04 LTS、systemd、root/sudo 权限。
2. 确认服务器架构：`uname -m`（支持 x86_64、aarch64）。
3. 确认公网 IP、云安全组权限和防火墙管理方式。
4. 备份旧 SSR：`/usr/local/shadowsocksr`、`/etc/shadowsocksr`、`/etc/init.d/ssr` 及当前防火墙规则。
5. 确认 8388/8389（或自定义端口）未被占用：`sudo ss -lntup`。
6. 不要在未备份旧服务的情况下覆盖安装。

## B. 安装

```bash
sudo apt-get update
sudo apt-get install -y unzip ca-certificates curl git python3 python3-venv
unzip ssr-ubuntu2204-dual-v2.0.0.zip
cd ssr-ubuntu2204-dual
sudo bash install.sh
```

选择安装 SSR、Rust SS 或双版本。安装器对现有目标目录采用 fail-closed 策略，不自动删除旧目录。

## C. 服务检查

```bash
sudo systemctl is-enabled ssr
sudo systemctl is-active ssr
sudo systemctl is-enabled shadowsocks-rust
sudo systemctl is-active shadowsocks-rust
sudo ss -lntup
sudo journalctl -u ssr -n 100 --no-pager
sudo journalctl -u shadowsocks-rust -n 100 --no-pager
```

仅安装其中一个版本时，另一个 unit 显示未安装属于预期结果。

## D. 防火墙

只放行实际安装并配置的端口。TCP 与 UDP 规则都需检查。云安全组、主机 UFW/nftables/iptables 必须一致。安装脚本不会更改现有防火墙规则。

## E. 客户端配置

- SSR 客户端：使用安装时生成的 SSR 密码、端口、method、protocol、obfs；客户端必须支持相同插件组合。
- Rust SS 客户端：使用 Shadowsocks 客户端，协议选择 Shadowsocks，method/password/port 与 `/etc/shadowsocks-rust/config.json` 完全一致。
- 两种协议不是互通协议。SSR 客户端不能按 SSR 节点方式连接 Rust SS 服务，反之亦然。
