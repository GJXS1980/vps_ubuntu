# 测试计划

## 1. 静态检查（安装前）

```bash
bash -n install.sh
bash -n manage.sh
bash -n bin/ssr-install.sh
bash -n bin/rust-install.sh
bash -n bin/uninstall-component.sh
bash -n tests/smoke-test.sh
python3 -m json.tool templates/ssr-config.example.json >/dev/null
python3 -m json.tool templates/rust-config.example.json >/dev/null
```

## 2. 安装测试

| ID | 场景 | 操作 | 预期 |
|---|---|---|---|
| INS-01 | 仅 SSR 安装 | 菜单选择 1 | 仅 ssr.service 启动 |
| INS-02 | 仅 Rust 安装 | 菜单选择 2 | 仅 shadowsocks-rust.service 启动 |
| INS-03 | 双版本安装 | 菜单选择 3 | 两个 unit 均启动且端口不同 |
| INS-04 | 目录冲突 | 预置目标目录后安装 | 安装器拒绝覆盖 |
| INS-05 | 不支持系统 | 非 Ubuntu 22.04 执行 | 明确退出 |
| INS-06 | 下载/校验失败 | 模拟 GitHub 不可达或 SHA256 错误 | 安装中止，不启动服务 |

## 3. 服务测试

| ID | 场景 | 操作 | 预期 |
|---|---|---|---|
| SVC-01 | 开机自启 | `systemctl is-enabled ssr` / `shadowsocks-rust` | 已安装服务为 enabled |
| SVC-02 | 重启 | `manage.sh restart` | 服务恢复 active |
| SVC-03 | 停止 | `manage.sh stop` | 对应服务 inactive |
| SVC-04 | 日志 | `manage.sh logs` | 可查看 journal |
| SVC-05 | 端口冲突 | 用其他程序占用监听端口 | 服务启动失败且日志可定位 |
| SVC-06 | 配置错误 | 备份后故意写入非法 JSON | 服务启动失败，日志指出配置错误 |

## 4. 网络与协议测试（必须使用真实客户端）

1. TCP：客户端连接成功，访问测试站点成功。
2. UDP：使用客户端支持的 UDP 测试验证 DNS/UDP 转发；不能仅凭 `ss -lun` 判断 UDP 协议成功。
3. SSR：逐项验证旧客户端实际使用的 method、protocol、obfs 组合。
4. Rust SS：使用 Shadowsocks 客户端和 AEAD method 验证。
5. 错误密码：应认证失败，不应建立有效代理会话。
6. 协议隔离：SSR 客户端连接 Rust 端口、SS 客户端连接 SSR 端口，预期均不能按错误协议建立会话。
7. 双实例：两服务同时运行时分别传输数据，互不影响。

## 5. 稳定性与资源

- 连续运行至少 24 小时。
- 记录 CPU、内存、进程重启次数、日志错误、TCP/UDP 可用性。
- 并发连接测试从低负载逐步增加，记录吞吐、时延、丢包和资源峰值。
- 重启 VPS 后确认已安装服务自动恢复。

## 6. 安全测试

- 配置文件权限应为 640，所有者 root，所属组为对应服务组。
- 服务进程不以 root 运行。
- systemd unit 启用 NoNewPrivileges、ProtectSystem、ProtectHome。
- 防火墙只开放必要端口。
- 管理操作仅限 sudo/root。
