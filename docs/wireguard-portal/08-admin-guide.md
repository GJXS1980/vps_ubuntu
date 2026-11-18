# 管理员手册
首个 super_admin 经 install-local 的交互命令生成。新增业务管理员用 docker compose run --rm api python -m app.maintenance admin；密码重置用 docker compose run --rm api python -m app.maintenance password 用户名。MFA 种子仅在私密终端登记，用当前动态码验证。super_admin 可设置注册模式、默认配额、保存 VPS 和管理备份；业务管理员可审批账号和操作设备。

“用户审核”搜索用户并点击行，检查邮箱、账号状态和配额后批准。停用账号立即撤销本地会话；已启用设备进入远端停用队列，VPS 不可达时既有隧道可能继续工作，务必检查任务和实际 Peer。恢复账号后单独决定恢复哪些设备。

“设备管理”支持启停、轮换和回收。回收先停用并确认远端任务完成，再确认删除。轮换影响当前 VPN，先通知设备持有者。“操作记录”可查看下载与任务。待确认任务退避重试；明确冲突后查实时状态和审核原因，再按任务重新同步。对账可立即触发，正常运行每约 30 秒执行一轮。外部 Peer 在“VPS 监控”显示为外部资源；经授权指定用户，再提交绑定。接管保留已有私钥，之前领过配置的人仍持有凭据；若需移交，应与原持有者协调轮换。

“系统设置”可下载加密快照。网页恢复需要 super_admin、CSRF、确认及 MFA，限定同版本与相同管理员 MFA，先写恢复前备份，再在事务内更换数据，撤销全部会话。恢复后核对历史绑定与 held 任务。跨主机迁移请按升级文档停机恢复。


调整现有账号角色可在私密控制台运行 docker compose run --rm api python -m app.maintenance grant-admin 用户名 或 revoke-admin 用户名。授予业务管理员需要登记或确认该账号的 MFA，并撤销旧会话。
