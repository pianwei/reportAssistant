# Xanadu 公网部署说明

## 当前部署

- 公网入口：`https://pianwei.shadlc.net/due-diligence/`
- 链路：公网入口 → WireGuard `wg-aliyun` → Xanadu 系统 Nginx → Dify Nginx → 应用容器。
- 应用目录：`/home/pianwei/apps/due-diligence-assistant`
- 当前容器：`due-diligence-assistant`
- 当前镜像：`due-diligence-assistant:20260810-public`
- 回滚容器：`due-diligence-assistant-pre-public-20260810`（已停止，保留旧镜像）。
- 重启策略：`unless-stopped`
- 宿主机监听：`127.0.0.1:8010`，不绕过 Nginx 直接开放端口。
- SQLite：`/home/pianwei/apps/due-diligence-assistant/runtime/app.db`
- 模型配置：`/home/pianwei/apps/due-diligence-assistant/.env`，权限 `600`。

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
