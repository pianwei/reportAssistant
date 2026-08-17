# 行内完整镜像部署包

本目录用于将尽调报告助手制作成一个完整、不可变的 OCI/Docker 镜像，并通过行内 RKE2 节点上的 nerdctl/containerd 单机运行。

## 目录说明

```text
deploy/docker/
├─ Dockerfile.intranet          # 完整应用镜像定义
├─ docker-compose.yml           # 行内 nerdctl compose 服务定义
├─ release.sh                   # 新服务器创建数据目录、导入镜像并启动
├─ .env.release.example         # 发布参数样例
├─ RELEASE-GUIDE.md             # 行内发布操作手册
├─ requirements-intranet.txt   # 固定的直接依赖
├─ wheelhouse/                  # Linux x86_64/Python 3.11 离线依赖
├─ .env.intranet.example       # 行内模型配置样例
├─ scripts/
│  ├─ build-and-save.ps1       # Windows 构建并导出镜像
│  ├─ build-and-save.sh        # Linux 构建并导出镜像
│  ├─ package-release.ps1      # 打包完整行内发布文件
│  └─ verify.sh                # 健康验证
└─ artifacts/                  # 镜像和完整发布包
```

镜像包含：

- FastAPI 后端；
- 已构建的前端静态资源；
- 293份脱敏报告数据；
- Python 3.11 运行环境；
- FastAPI、HTTPX、Pydantic、Cryptography、PyMySQL、Uvicorn等全部运行依赖。

镜像不包含真实模型地址、API Key、MySQL 密码和日志。业务数据保存在外部 MySQL，容器无需挂载可写数据目录。

完整操作见 [RELEASE-GUIDE.md](./RELEASE-GUIDE.md)。

## 按行内 release.sh 发布

将镜像 tar、`docker-compose.yml`、`release.sh`、`.env.intranet` 和可选的
`.env.release` 放在同一发布目录。首次发布前执行：

```bash
cp .env.intranet.example .env.intranet
cp .env.release.example .env.release
vi .env.intranet
vi .env.release
chmod 750 release.sh
./release.sh
```

脚本会启用 Bash alias 展开，并加载 `~/.bash_profile` 和发布目录中的
`.envs_shell`，直接使用行内已有的 `nerdctl` alias。首次发布时会加载新镜像，再通过 `nerdctl compose` 启动服务。
