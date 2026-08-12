# Xanadu 公网部署说明

## 当前部署

- 公网入口：`https://pianwei.shadlc.net/due-diligence/`
- 链路：公网入口 → WireGuard `wg-aliyun` → Xanadu 系统 Nginx → Dify Nginx → 应用容器。
- 应用目录：`/home/pianwei/apps/due-diligence-assistant`
- 当前容器：`due-diligence-assistant`
- 当前镜像：`due-diligence-assistant:20260812-session-filter-v4`。
- 当前数据：293 份报告、5860 个标签。
- 当前回滚容器：`due-diligence-assistant-pre-session-filter-20260812`（已停止，镜像为 `due-diligence-assistant:20260812-shared-interaction-v3`）。
- 重启策略：`unless-stopped`
- 宿主机监听：`127.0.0.1:8010`，不绕过 Nginx 直接开放端口。
- SQLite：`/home/pianwei/apps/due-diligence-assistant/runtime/app.db`
- 模型配置：`/home/pianwei/apps/due-diligence-assistant/.env`，权限 `600`。
- 当前模型：`deepseek-v4-flash`，思考模式关闭。

## 公网访问

- 移动端：<https://pianwei.shadlc.net/due-diligence/>
- 运营端：<https://pianwei.shadlc.net/due-diligence/ops>
- 健康检查：<https://pianwei.shadlc.net/due-diligence/api/v1/health>

移动端和公共聊天接口可直接访问。运营页面 `/ops` 和全部
`/api/v1/ops/*` 接口由 Nginx Basic Auth 保护。

运营端用户名为 `opsadmin`。密码不写入仓库或部署日志，可通过 SSH 读取一次：

```powershell
ssh xanadu "cat /home/pianwei/apps/due-diligence-assistant/ops-basic-auth-password.txt"
```

确认已安全保存密码后，可以手动删除服务器上的明文密码文件；Nginx 使用的仅是密码摘要：

```powershell
ssh xanadu "rm -f /home/pianwei/apps/due-diligence-assistant/ops-basic-auth-password.txt"
```

## Nginx 配置

- 配置目录：`/home/pianwei/Dify/dify/docker/nginx/conf.d`
- 认证摘要：`due-diligence.htpasswd`
- 配置脚本：`deploy/xanadu/configure_public_proxy.py`
- 每次修改前的备份位于应用目录的 `nginx-backups/`。

修改配置后必须先检查再热加载：

```powershell
ssh xanadu "docker exec docker-nginx-1 nginx -t"
ssh xanadu "docker exec docker-nginx-1 nginx -s reload"
```

## 运维命令

```powershell
ssh xanadu "docker ps --filter name=due-diligence-assistant"
ssh xanadu "docker logs --tail 100 due-diligence-assistant"
ssh xanadu "docker restart due-diligence-assistant"
ssh xanadu "curl -fsS http://127.0.0.1:8010/api/v1/health"
ssh xanadu "python3 /home/pianwei/apps/due-diligence-assistant/verify_public.py"
```

公网版本构建时使用：

```powershell
$env:VITE_BASE_PATH='/due-diligence/'
$env:VITE_API_BASE_URL='/due-diligence/api/v1'
Set-Location frontend
npm run build
```

报告数据来自镜像内的 `data/**/*.json`。修改报告后需要重新构建镜像并重建容器；会话、消息、运营模型配置和 SQLite 数据保存在宿主机 `runtime` 目录，不随镜像更新丢失。

## 2026-08-11 前端 UI 发布

- 发布脚本：`deploy/xanadu/switch_ui_competition_release.sh`
- 覆盖镜像定义：`deploy/xanadu/ui-overlay.Dockerfile`
- 发布内容：仅替换当前稳定镜像中的 `/app/frontend/dist`，不包含工作区其他后端改动。
- 公网验证：主页、静态资源、健康接口均为 `200`；运营页匿名访问为 `401`，认证后的运营页和运营 API 均为 `200`。

## 2026-08-11 数据发布

- 发布脚本：`deploy/xanadu/switch_data293_release.sh`
- 数据覆盖镜像定义：`deploy/xanadu/data-overlay.Dockerfile`
- 发布镜像：`due-diligence-assistant:20260811-data293-v2`
- 数据覆盖前先删除基础镜像中的旧 `/app/data`，避免已从本地删除的旧报告残留。
- 启动校验：293 份报告、5860 个标签，模型状态为 `configured`。
- 公网验证：主页、静态资源、健康接口均为 `200`；运营页匿名访问为 `401`，认证后的运营页和运营 API 均为 `200`。

## 2026-08-12 多轮与统计修复发布

- 发布脚本：`deploy/xanadu/switch_multiturn_statistics_release.sh`
- 发布镜像：`due-diligence-assistant:20260812-multiturn-statistics-v2`
- 案例推荐和多维筛选功能卡共用多轮标签补充流程。
- “各行业报告数量”等分组统计使用全量标签在后端聚合，不调用条件报告匹配模型。
- “推荐几份/一些/若干篇”等表达保持推荐意图，最多返回 3 份排序结果。
- 行业原始标签归并到标准行业大类；初创、创业、早期企业按小微企业语义参与匹配。
- 公网抽查：行业统计覆盖全部 293 份报告并归并为 17 类；初创企业推荐返回 3 份报告。

> 上述 `multiturn-statistics-v2` 已回滚，不是当前运行版本。

## 2026-08-12 推荐与筛选交互统一发布

- 发布脚本：`deploy/xanadu/switch_shared_interaction_release.sh`
- 发布镜像：`due-diligence-assistant:20260812-shared-interaction-v3`
- UI 保持不变，案例推荐与多维筛选使用相同的引导卡和对话输入交互。
- 案例推荐按匹配度返回 Top 3；多维筛选按全部标签条件精确筛选并返回全部命中报告。
- 公网抽查“小微企业”：推荐返回 3 份，筛选返回 92 份。

## 2026-08-12 会话字段累加与新筛选发布

- 发布脚本：`deploy/xanadu/switch_session_filter_release.sh`
- 发布镜像：`due-diligence-assistant:20260812-session-filter-v4`
- 同一 `session_id` 内继续维护和累加报告匹配标签；未明确切换功能时保持当前推荐或筛选模式。
- 每次补充字段后立即返回结果：推荐 Top 3，筛选返回全部严格命中。
- 报告结果衍生区增加“新筛选”气泡；点击后清空标签，仅提示“你有什么其他想要了解的尽调报告吗？”，不返回报告。
- 公网抽查：制造业 62 份，补充小微企业后 21 份；新筛选后无结果且标签清空，再输入小微企业返回 92 份。
