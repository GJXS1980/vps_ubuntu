# SQLite 与迁移
backend/alembic/versions 为版本化 DDL，SQLAlchemy Engine 管理连接；业务事务通过同一连接使用参数化 SQL。启用 WAL、foreign_keys 和 45 秒写锁等待。读操作使用快照，涉及配额、归属变更、领取和任务的写入使用 BEGIN IMMEDIATE。Worker 在一次写事务内验证操作回执并绑定设备。远端慢时会延长本地写等待，适用小型单机平台。

|表|关键字段及约束|
|---|---|
|users|username、email 不区分大小写且唯一，注册时规范化；hash、status、verified、quota、otp_step|
|roles / user_roles|三个固定角色，user 主键限制每人一个有效角色|
|sessions|随机标识仅存 digest，user、csrf、expires；按用户索引撤销|
|tokens / attempts|一次性凭证摘要、用途、过期时间；限流窗口与计数|
|vpn_servers|唯一名称和管理 IPv4、最近探测时间与健康状态，证书按地址在数据库外管理|
|devices|随机 UUID、所有者、VPS、名称、状态、最近采样；未回收设备名称在账号内唯一|
|wireguard_peers|device 主键，(server,peer) 唯一，完整公钥指纹和 VPS 返回的地址|
|provision_jobs|UUID 幂等键主键，固定请求参数、状态、重试次数、到期时间、摘要错误；每台设备最多一个 pending 任务|
|download_events|用户、设备、模式、格式、领取时间；无配置正文|
|audit_logs|操作人、动作、目标及时间|
|app_settings|注册策略与新账号配额|

首次迁移 001 建表，002 增加节点监测字段。升级使用 alembic upgrade head。备份使用 SQLite backup API 获取一致快照，清除会话和一次性凭证，再连同 MFA 种子加密；解密密钥、VPS 凭据和 HTTPS 私钥需分开保管。数据目录不用于共享网盘或多主部署。
