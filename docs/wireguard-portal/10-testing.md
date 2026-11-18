# 自动化结果与现场验收

2026-11-18，Windows / Python 3.11 / 本机 Chrome。旧系统基线 e5ff00b。测试使用临时目录、虚构的客户端密钥和专用测试数据库。实际使用回环 HTTPS 和 TLS 客户端证书测试认证。Mock 操作经过真实后端任务表、旧分配函数、状态文件提交、配置渲染和 Agent 归属检查。

|已运行的命令|结果|
|---|---|
|python -m pytest -q --basetemp=独立临时目录 -p no:cacheprovider wireguard-portal/backend/tests tests|84 通过，0 失败；30 个新用例，54 个原仓库用例。Starlette TestClient 有 1 个依赖弃用提示|
|python -m unittest discover -s tests -q|54 通过，0 失败；与上一行旧用例重叠|
|npm run build|vue-tsc --noEmit 和 Vite 生产构建通过。打包器提示单个 JS chunk 超过默认 500 kB|
|npm run lint|ESLint 通过|
|npm run e2e|3 通过，0 失败。覆盖待审账号、管理员审批至双模式下载与二维码、390 像素宽度注册页|
|python -m ruff check --select F wireguard-portal；python -m compileall -q wireguard-portal/agent wireguard-portal/backend wireguard-portal/scripts|通过|
|bash -n 对 10 个 shell 脚本逐个检查；PowerShell Parser 检查安装脚本|语法通过|
|management-link.py 创建临时凭据，openssl verify 分别验证 sslserver 与 sslclient|均通过；对已有目标重复生成被拒，原私钥摘要相同|

开发过程中发现并修复过期证书测试中并置信任根的识别问题。原 SSR 的 external_origin_rejected 曾在 Windows 合并测试中出现 WinError 10053；该测试单跑通过，最终全量运行也通过。未修改 SSR 服务或放宽断言。前端依赖在临时构建目录安装，因为本机 npm 不能直接在检出目录创建 node_modules。

## 复跑

从仓库根目录开始，以下使用当前已激活的 Python 虚拟环境，避免写系统 Python：

```bash
python -m pip install -r wireguard-portal/backend/requirements.txt
python -m pytest -q wireguard-portal/backend/tests tests
cd wireguard-portal/frontend
npm ci
npm run build
npm run lint
npx playwright install chromium
npm run e2e
```

已安装 Chrome 时可设置 PORTAL_CHROME 为其可执行文件绝对路径。浏览器测试会启动独立回环 HTTPS 服务，默认端口 17444（可用 PORTAL_TEST_PORT 修改）。临时测试数据与管理员凭据在测试环境生成。仅此浏览器测试上下文信任测试自签服务；业务 Agent 客户端始终验证证书。Windows 环境可通过 PORTAL_BROWSER_SERVER 显式指定虚拟环境 python.exe、backend/tests/browser_server.py 和构建后的 dist。

## 覆盖范围

- 账号审核、四种注册模式、重复用户名/邮箱、弱密码、限流、会话固定与撤销、MFA、角色与资源归属、模拟验证邮件与一次性重置码。
- 设备配额、无容量、管理连接失败、不兼容版本、并发相同请求、远端提交后丢响应、本地提交失败、按原回执恢复、明确拒绝与人工重试、外部删除/停用、历史 Peer 接管。
- 两种配置原文与二维码、无缓存、日志中无测试私钥、拒绝其他用户/无登录/停用设备/过期指纹、轮换和回收。账号停用立即撤销访问。
- 有效和缺失客户端证书、过期客户端证书、不受信的服务端 CA、错误源地址、非法参数和无效 Peer 标识。Windows 临时测试未执行 Linux 的 sudo 或 flock 系统调用。
- 受保护初始化重复执行、保留既有行的数据库升级、数据库重新打开、加密备份和还原、错误备份拒绝与会话失效。

## 真实部署验收（未执行）

使用一次性 Ubuntu 22.04 VPS、两个新的测试门户账号和专用测试设备。以下步骤会产生测试 Peer，并在指定步骤使测试设备断线。保存测试编号，避免选择原有客户。

1. 依 05 和 06 安装平台及管理链路。记录测试前 sudo wgvps-users list、sudo wg show wgvps peers 和旧 /admin 的登录响应；不要导出全量 bundle 或记录私钥。
2. 两次执行本地安装脚本，检查 docker compose ps、/api/health、alembic current 以及只有一个初始 super_admin。重复运行 VPS 安装脚本，在独立管理连接内验证 /v1/health 与 /v1/capacity，并确认旧管理服务仍为 active。
3. A、B 各自注册；管理员批准 A 并保留 B 待审。A 登录后申请测试手机，查看设备号、回执、VPS 返回的地址。用 sudo wgvps-users list 及 sudo wg show wgvps peers 对照新增数量应为一。相同 Idempotency-Key 重放同一申请，设备号和任务号应相同。
4. 导入 A 的 global 配置，在测试客户端访问允许的测试目的地；切换到 proxy 后，经 10.66.77.1:1080 测试 SOCKS5。观察 sudo wg show wgvps latest-handshakes 和 sudo wg show wgvps transfer，再核对门户采样；分别用移动客户端扫描两种二维码。批准 B 后应无法用 B 的会话领取 A 的配置。
5. 在测试环境停止 wg-portal-agent，确认本地可登录，节点出现异常；恢复 Agent 并对账。分别重启测试 API、Worker、Agent 和 VPS，核对数据库、原 Peer、待处理任务、监控采样。仅在隔离环境测试断电。
6. 在旧管理页停用新建的测试 Peer，确认新门户拒绝领取。恢复后从门户轮换，仅测试设备旧配置应失去握手；重新导入后恢复。回收先停用后删除，再核对测试前的 Peer 列表与旧 /admin 功能。
7. 备份并在隔离副本上恢复，核对账号、MFA、设备、任务和领取记录；旧会话应失效。测试迁移、升级、卸载 Agent 后的旧服务可用性。用真实 SMTP 做投递和重置。将环境版本、命令退出码、脱敏状态和结果填入部署记录。

未提供真实 VPS、Docker daemon、生产证书或 SMTP 账号，以上现场步骤均待执行。
