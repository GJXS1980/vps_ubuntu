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

## 7. SSR 管理器验收

运行 `python3 -m unittest discover -s tests -p 'test_admin.py' -v`；这些测试模拟内核和 QR 编码器，不代表实机通过。

Ubuntu 22.04 测试机必须进一步验证：

| 场景 | 操作与预期 |
|---|---|
| Web 安装 | admin-install 后两个管理 unit active；仅 127.0.0.1:9080 监听；SSH 隧道可访问 |
| HTTP 认证 | 无令牌/错误令牌拒绝；正确令牌可操作；外站 Origin 拒绝 |
| 多账号 | 添加两个端口；重启后都能连接；删除一个不影响另一个配置；拒绝删除最后一个 |
| 独立限速 | 两账号设置不同限速，真实 TCP 并发测吞吐；同端口 IPv4/IPv6 合计每方向不超过所设速率（允许短时突发） |
| 设备上限 | auth_sha1_v4 设置 2；三个独立客户端进程产生不同标识，第三个应拒绝；IPv4/IPv6 混合测试；静默约三分钟后可释放 |
| UDP 限制 | 设置限速或设备限制后 UDP 不监听；两项都解除并重启后 UDP 恢复；不接受 UDP 绕过限额 |
| 分享扫码 | 扫描终端/Web QR；实际端口、密码、协议、混淆匹配；IPv6 SSR 导入测试；origin/plain 额外测 SS |
| BBR 回退 | 记录原 sysctl 与专属文件；启用后值为 bbr/fq；重复启用后关闭仍恢复初始值；重启验证持久化 |
| SMTP 作用域 | SSR 代理出口 TCP 25/465/587 拒绝；非 ssr 用户的允许流量与 SSH 不受影响；IPv4/IPv6 分别验证 |
| BT/PT | 使用自建测试服务验证默认端口/特征拦截；记录加密、分段、非标准端口漏检；不要把漏检视为完整 DPI 已实现 |
| 规则回退 | 在隔离测试机模拟 IPv6 规则失败，IPv4 自有链恢复，其他防火墙链不变 |
| 开机恢复 | 重启机器后规则恢复；重载 UFW 后重启 ssr-admin-firewall 并核对 runtime 状态 |
| 锐速 | 无包/哈希错误/内核不匹配均拒绝执行；只有供应商验证的包才能测试安装；安装后另验模块、授权和性能 |

尚未在真实 Ubuntu VPS 完成以上验收，不应将单元测试结果记录为生产验收通过。
