# 行内后端 + MySQL 全量数据 + 运营端部署手册

## 1. 适用范围

本包用于在 Linux x86_64 行内服务器离线部署：

- 应用镜像：`due-diligence-assistant:20260817-mysql-ops-v2`；
- 数据库镜像：`mysql:8.4`；
- 后端 API、移动端首页和“立功竞赛运营管理平台”；
- 当前 MySQL 全量结构和数据。

部署方式沿用 `deploy/docker` 已成功验证的镜像加载和 compose 启动流程。支持标准 Docker Compose；也支持已在 `~/.bash_profile` 配置好权限和 socket 的行内 nerdctl。

## 2. 发布包结构

```text
docker-compose.yml
release.sh
.env.release.example
.env.intranet.example
SHA256SUMS
MIGRATION-MANIFEST.md
images/
├─ due-diligence-assistant-20260817-mysql-ops-v2.image.tar
└─ mysql-8.4.image.tar
database/
└─ 001-due_diligence-full.sql
scripts/
├─ verify.sh
├─ backup.sh
└─ restore.sh
```

## 3. 服务器要求

- Linux x86_64，磁盘至少预留 8GB；
- Docker 24+ 与 Docker Compose v2，或已验证可运行 compose 的 nerdctl；
- 发布账号可以加载镜像、创建 bridge 网络和 named volume；
- 应用端口默认 `8888` 未被占用；
- 容器可以访问行内大模型地址。

MySQL 不映射宿主机端口，只能由同一 compose 网络中的应用访问。

## 4. 解压与完整性校验

```bash
unzip due-diligence-assistant-20260817-mysql-ops-v2-full-release.zip \
  -d due-diligence-assistant-20260817-mysql-ops-v2
cd due-diligence-assistant-20260817-mysql-ops-v2
sha256sum -c SHA256SUMS
```

所有项目必须显示 `OK`。任何文件校验失败都应停止发布并重新传输。

## 5. 配置

```bash
cp .env.release.example .env.release
cp .env.intranet.example .env.intranet
chmod 600 .env.release .env.intranet
vi .env.release
vi .env.intranet
chmod 750 release.sh scripts/*.sh
```

### 5.1 容器与 MySQL 配置

标准 Docker 设置：

```dotenv
CONTAINER_CLI=docker
MYSQL_USER=due_diligence
MYSQL_PASSWORD=实际强密码
MYSQL_ROOT_PASSWORD=另一条实际强密码
APP_PORT=8888
```

行内 nerdctl 设置：

```dotenv
CONTAINER_CLI=nerdctl
CONTAINER_NAMESPACE=k8s.io
```

脚本会先加载 `~/.bash_profile`，因此可继续使用原成功部署环境中的 nerdctl alias。

### 5.2 应用配置

`.env.intranet` 中的数据库主机固定为 compose 服务名 `mysql`：

```dotenv
DATABASE_URL=mysql://due_diligence:URL编码后的同一业务密码@mysql:3306/due_diligence?charset=utf8mb4
LLM_BASE_URL=https://实际行内模型地址/v1
LLM_MODEL=实际模型名称
LLM_API_KEY=实际密钥或留空
CORS_ORIGINS=http://实际服务器IP:8888
```

`MYSQL_PASSWORD` 是原始密码，`DATABASE_URL` 中必须填写其 URL 编码形式。包含 `@/:#%` 等字符时不可直接复制原始值。

发布脚本会按 Bash 环境文件读取配置，因此密码不要包含空格、换行或 `#`；推荐使用大小写字母、数字、下划线和连字符组合。

如需在运营端保存模型 API Key，生成 Fernet 主密钥并填写：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```dotenv
MODEL_CONFIG_MASTER_KEY=生成结果
MODEL_PROFILE_FROM_DATABASE=true
```

主密钥必须单独备份；丢失后数据库中已有模型密钥无法解密。

## 6. 首次发布与数据导入

首次发布保持：

```dotenv
REQUIRE_EMPTY_DATABASE_VOLUME=true
```

然后执行：

```bash
./release.sh
```

脚本依次完成：

1. 校验镜像、SQL 和脚本；
2. 阻止在已有同名 MySQL 数据卷上误执行首次迁移；
3. 离线加载 MySQL 与应用镜像；
4. 创建专用网络和 MySQL named volume；
5. MySQL 首次初始化时导入 `001-due_diligence-full.sql`；
6. MySQL 健康后启动非 root、只读文件系统的应用容器；
7. 等待应用 `/api/v1/health/ready` 通过。

SQL 只在空 MySQL 数据卷第一次初始化时导入。后续重启不会重复导入或覆盖数据。

## 7. 验证

```bash
./scripts/verify.sh http://127.0.0.1:8888
```

脚本会验证三个健康接口、运营端入口，并核对全部 8 张表：

- reports = 293；
- report_tags = 5860；
- sessions = 2；
- messages = 4；
- session_tags = 2；
- suggestion_batches = 6；
- model_profiles = 0；
- model_events = 0。

浏览器访问：

```text
http://服务器IP:8888/
http://服务器IP:8888/ops
http://服务器IP:8888/api/v1/health
```

运营端标题应显示“立功竞赛运营管理平台”。

在“对话历史”中确认“过去 1 天 / 3 天 / 7 天 / 30 天 / 全部”能够切换，默认选择过去 7 天；“导出当前结果”应下载遵循当前用户、关键词、功能和时间条件的完整 CSV 日志。

## 8. 后续应用升级

数据库已经初始化后，把 `.env.release` 修改为：

```dotenv
REQUIRE_EMPTY_DATABASE_VOLUME=false
```

加载新应用镜像并再次执行 `./release.sh`。named volume 会继续复用，SQL 初始化文件不会再次执行。

## 9. 数据备份

升级、恢复或服务器维护前执行：

```bash
./scripts/backup.sh
```

输出位于 `backups/*.sql.gz`，同时生成 SHA-256 文件。建议将备份复制到服务器外的受控存储。

## 10. 数据恢复

恢复会清空目标数据库，必须先确认备份校验值：

```bash
sha256sum -c backups/备份文件.sql.gz.sha256
./scripts/restore.sh backups/备份文件.sql.gz
```

按提示输入 `RESTORE` 后，脚本停止应用、重建数据库、导入备份并重新启动应用。完成后必须再次执行 `verify.sh`。

## 11. 日常运维

Docker：

```bash
docker compose --env-file .env.release -p due-diligence-assistant ps
docker logs --tail 200 due-diligence-assistant
docker logs --tail 200 due-diligence-mysql
```

nerdctl：

```bash
nerdctl -n k8s.io compose --env-file .env.release -p due-diligence-assistant ps
nerdctl -n k8s.io logs --tail 200 due-diligence-assistant
nerdctl -n k8s.io logs --tail 200 due-diligence-mysql
```

不要手工修改 MySQL volume 内容，也不要用 `chmod 777` 解决权限问题。

## 12. 回滚原则

- 仅回滚应用：保留 MySQL volume，加载旧应用镜像并修改 `APP_IMAGE` 后重新发布；
- 同时回滚数据：先备份当前库，再使用目标版本 SQL 备份执行 `restore.sh`；
- 不要仅删除容器后手工搬运 `/var/lib/mysql`，跨版本直接复制数据目录可能导致不可恢复损坏。
