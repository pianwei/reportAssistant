# 数据迁移清单

快照来源：本地 MySQL 8.4 `due_diligence` 数据库。

| 对象 | 数量 |
|---|---:|
| reports | 293 |
| report_tags | 5860 |
| sessions | 2 |
| messages | 4 |
| session_tags | 2 |
| suggestion_batches | 6 |
| model_profiles | 0 |
| model_events | 0 |

SQL 文件：`database/001-due_diligence-full.sql`

该快照包含表结构、索引和全部表数据。应用启动后会根据镜像内的 293 份 JSON 报告原子校验并重建 `reports`、`report_tags`，会话、消息、会话标签、建议批次和模型配置数据保持迁移值。

2026-08-17 已使用独立 compose 项目和全新 named volume 完成恢复演练：MySQL 与应用健康检查通过，8 张表数量与本清单一致，`/` 与 `/ops` 均返回 HTTP 200。演练容器、网络和临时数据卷已在验证后清理。
