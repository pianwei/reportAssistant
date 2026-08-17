# 尽调报告助手行内 Docker 发布操作手册

## 1. 发布包内容

```text
due-diligence-assistant-20260814-intranet-v1.image.tar  # 应用镜像
SHA256SUMS                                              # 镜像校验值
docker-compose.yml                                      # compose 配置
release.sh                                              # 行内发布脚本
.env.intranet.example                                   # 应用配置模板
.env.release.example                                    # 发布参数模板
verify.sh                                               # 服务验证脚本
README.md                                               # 部署方式说明
```

## 2. 解压和校验

```bash
unzip due-diligence-assistant-20260814-intranet-v1-release.zip \
  -d due-diligence-assistant-20260814-intranet-v1
cd due-diligence-assistant-20260814-intranet-v1
sha256sum -c SHA256SUMS
```

校验结果必须显示 `OK`。

## 3. 准备配置

```bash
cp .env.intranet.example .env.intranet
cp .env.release.example .env.release
vi .env.intranet
vi .env.release
chmod 750 release.sh verify.sh
```

`.env.intranet` 至少填写 MySQL、真实的模型地址、模型名称、密钥和访问地址：

```dotenv
DATABASE_URL=mysql://用户:经URL编码的密码@MySQL主机:3306/due_diligence?charset=utf8mb4
LLM_BASE_URL=https://实际行内模型地址/v1
LLM_MODEL=实际模型名称
LLM_API_KEY=实际密钥或留空
CORS_ORIGINS=http://实际服务器IP:8888
```

`.env.release` 中确认镜像名称、镜像包名称和端口：

```dotenv
APP_IMAGE=docker.io/library/due-diligence-assistant:20260814-intranet-v1
IMAGE_ARCHIVE=due-diligence-assistant-20260814-intranet-v1.image.tar
APP_PORT=8888
```

脚本会加载 `~/.bash_profile` 和发布目录中的 `.envs_shell`，并直接调用其中定义的
`nerdctl` alias。alias 应包含行内所需的 `sudo`、RKE2 containerd socket 和
`k8s.io` namespace。使用发布账号直接运行脚本，不要在脚本外层再加 `sudo`。

发布前可确认：

```bash
source ~/.bash_profile
source ./.envs_shell 2>/dev/null || true
type nerdctl
nerdctl info
```

## 4. 执行发布

```bash
./release.sh
```

脚本依次加载新镜像，并执行 `nerdctl compose -f docker-compose.yml up -d`。应用不创建或挂载本地数据库目录。

## 5. 发布后验证

```bash
./verify.sh http://127.0.0.1:8888
```

浏览器访问：

```text
http://服务器IP:8888/
http://服务器IP:8888/ops
http://服务器IP:8888/api/v1/health
```
