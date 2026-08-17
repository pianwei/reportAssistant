# 立功竞赛运营管理平台行内完整迁移包

该目录在已成功部署的 `deploy/docker` 基础上扩展为双镜像离线迁移包，包含：

- FastAPI 后端、293 份报告 JSON 和已构建的移动端/运营端；
- MySQL 8.4 官方镜像；
- 8 张业务表及全部数据的 MySQL 一致性快照；
- Docker Compose / nerdctl compose 编排；
- 发布、健康验证、备份和人工确认恢复脚本。

最终交付包与 SHA-256 位于 `artifacts/`。完整步骤见 [OPERATIONS-GUIDE.md](./OPERATIONS-GUIDE.md)。
