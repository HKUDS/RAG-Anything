# 火山引擎云服务器部署指南（Docker Compose）

> 适用：已知火山引擎 ECS 的公网 IP、登录用户名与密码，把本仓库以 Docker Compose 方式部署到单台 Linux 服务器。
> 主路径：Docker Compose（`docker-compose.yml` 自带 PostgreSQL、Redis、迁移任务、FastAPI 应用与 nginx 前端，一行命令拉起）。
> 裸机 systemd 方式（自备 PostgreSQL/Redis）见 [rag-anything.service](rag-anything.service) 与下文第 8 节。

## 0. 前置条件

- ECS 规格建议：Linux（Ubuntu 22.04/Debian 12/Anolis），≥4 vCPU、≥8 GB 内存（postgres 容器 mem_limit 4g）、系统盘 ≥100 GB（`uploads/`、`rag_storage/`、向量数据会持续增长）。
- 需在火山引擎控制台「安全组」放行入方向：`TCP 22`（SSH）、`TCP 80`（HTTP）、`TCP 443`（HTTPS，可选）。
- 不需要对公网开放 `8000`/`5432`/`6379`。
- 公网入口是 nginx 容器的 `80` 端口（静态前端 + `/api` 反代 + `/ws` WebSocket）。

## 1. SSH 登录

```bash
ssh root@<服务器公网IP>
```

- 火山引擎 Linux 镜像默认用户名通常是 `root`；「实例 ID」仅用于控制台操作，登录用用户名。
- 也可在火山引擎控制台使用「远程连接 / Workbench」。

## 2. 安装 Docker 与 Compose 插件

```bash
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker compose version   # 确认 Compose v2 已可用
```

国内网络建议配置镜像加速，编辑 `/etc/docker/daemon.json`：

```json
{
  "registry-mirrors": ["https://docker.m.daocloud.io", "https://docker.1ms.run"]
}
```

```bash
systemctl restart docker
```

若 `get.docker.com` 不可达，改用系统源安装：

```bash
apt-get update && apt-get install -y docker.io docker-compose-plugin
systemctl enable --now docker
```

## 3. 把代码放到服务器

`.env` 已被 `.gitignore`/`.dockerignore` 排除，密钥不会进入仓库或镜像。

方式 A（推荐，只传已提交文件）：

```bash
# 本机执行
git archive -o rag-anything.tar HEAD
scp rag-anything.tar root@<服务器公网IP>:/opt/
# 服务器执行
mkdir -p /opt/rag-anything && cd /opt/rag-anything && tar xf /opt/rag-anything.tar
```

方式 B（需包含未提交改动，本机执行）：

```bash
rsync -a --exclude={.venv,node_modules,rag_storage*,uploads,output,__pycache__,.git} ./ root@<服务器公网IP>:/opt/rag-anything/
```

方式 C（GitHub 可达时）：

```bash
git clone https://github.com/619916cgh/RAG-Anything.git /opt/rag-anything
```

## 4. 配置 .env

```bash
cd /opt/rag-anything
cp .env.example .env
vi .env
```

### 必填项（`RAGANYTHING_ENV=production` 时启动校验强制）

| 变量 | 说明 |
|---|---|
| `RAGANYTHING_ENV` | 固定 `production` |
| `DATABASE_URL` | 容器内连接串，host 必须写 `postgres`（compose 服务名），如 `postgresql://raganything:密码@postgres:5432/raganything` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DATABASE` | 与 `DATABASE_URL` 一致 |
| `JWT_SECRET` / `JWT_REFRESH_SECRET` | 各 ≥32 位随机串，`openssl rand -hex 32` 生成 |
| `DEFAULT_ADMIN_USERNAME` / `DEFAULT_ADMIN_PASSWORD` | 初始管理员；生产模式不允许空密码 |
| `MIGRATION_BACKUP_ACKNOWLEDGED` | 迁移安全闸门，必须 `true`；全新空库无需备份，已有数据必须先 `pg_dump` 备份再置 true |
| `LLM_BINDING_API_KEY` | LLM/VLM/文本 embedding 共用的 OpenAI 兼容 Key（DashScope、火山方舟等） |
| `LLM_BINDING_HOST` | 如 `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `VISION_EMBEDDING_API_KEY` | 生产校验会检查视觉模型目录的 `api_key_env`，填入同一 Key 即可 |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | 默认 `text-embedding-v3` / `1024`，须与向量库既有数据一致 |

最小示例（全部替换占位符）：

```bash
RAGANYTHING_ENV=production
PORT=8000
JWT_SECRET=<openssl rand -hex 32>
JWT_REFRESH_SECRET=<openssl rand -hex 32>
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=<你的强密码>
DATABASE_URL=postgresql://raganything:dbpass123@postgres:5432/raganything
POSTGRES_USER=raganything
POSTGRES_PASSWORD=dbpass123
POSTGRES_DATABASE=raganything
MIGRATION_BACKUP_ACKNOWLEDGED=true
LLM_BINDING_API_KEY=sk-xxx
LLM_BINDING_HOST=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
VISION_MODEL=qwen-vl-plus
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_DIM=1024
VISION_EMBEDDING_API_KEY=sk-xxx
```

可选但建议关注：`CORS_ORIGINS`、`MAX_ASYNC`、`ENTITY_EXTRACT_CONCURRENCY`、`POSTGRES_HNSW_M`、`POSTGRES_HNSW_EF`（HNSW 恢复档，默认已开启低并发）。

## 5. 构建并启动

```bash
cd /opt/rag-anything
# 国内网络建议加国内源构建参数，加快 apt/pip 下载
docker compose build \
  --build-arg DEBIAN_MIRROR_HOST=mirrors.aliyun.com \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
docker compose up -d
docker compose ps
docker compose logs -f migrate app
```

启动顺序：`postgres`（健康检查通过）→ `migrate`（`scripts/pg_migration_runner.py apply` 自动应用 `migrations/001..032`）→ `app` → `nginx`。

- `migrate` 容器退出码 2：`MIGRATION_BACKUP_ACKNOWLEDGED` 未置 `true`。
- 首次构建会安装 LibreOffice/ffmpeg 等原生依赖，耗时较长属正常。

## 6. 放行端口并验证

- 控制台 → 云服务器 → 安全组 → 入方向规则：放行 `TCP 80`（及 `443`）。
- 浏览器访问 `http://<公网IP>/`。
- 健康检查：`curl http://<公网IP>/api/health`（容器内 HEALTHCHECK 同路径）。
- 使用 `DEFAULT_ADMIN_USERNAME`/`DEFAULT_ADMIN_PASSWORD` 登录。
- 若登录页打不开但接口 502：`docker compose logs nginx app` 排查；应用容器内数据库地址必须是 `postgres:5432`，不能写 `localhost` 或公网 IP。

## 7. HTTPS（可选）

- 有域名：控制台解析 A 记录后，用 certbot 签发证书，并由宿主 nginx/caddy 反代到 `127.0.0.1:80`；或给 nginx 容器挂载证书并映射 `443`。
- 无域名：保持 HTTP 即可，nginx 已内置安全响应头。

## 8. 数据与运维

- 数据持久化：`pgdata`/`redisdata` 命名卷 + 宿主目录挂载 `./rag_storage`、`./uploads`、`./output`。
- 数据库备份：

```bash
docker compose exec postgres pg_dump -U raganything raganything -Fc > backup_$(date +%F).dump
```

- 升级发布：`git pull` → `docker compose build` → `docker compose up -d`；新增迁移由 `migrate` 自动执行，升级前先备份并保持 `MIGRATION_BACKUP_ACKNOWLEDGED=true`。
- 日志：`docker compose logs -f app`；磁盘告警默认阈值 `DISK_ALERT_THRESHOLD_MB=10240` / `DISK_ALERT_PERCENT=85`。
- 裸机 systemd 方案：自备 PostgreSQL/Redis 与 `.venv`，使用 [deploy/rag-anything.service](rag-anything.service)（`ExecStart=.venv/bin/python server.py --workers 4`）。

## 9. 常见问题

| 现象 | 处理 |
|---|---|
| 启动失败 `missing required production configuration: ...` | 按第 4 节补齐变量；`.env` 变更后需 `docker compose up -d` 重建容器 |
| `migrate` 退出码 2 | 置 `MIGRATION_BACKUP_ACKNOWLEDGED=true`（已有数据先备份） |
| 上传大文件报 413 | `nginx.conf` 已设 `client_max_body_size 500m`，自定义配置时保持同步 |
| 内存不足/启动 OOM | 内存建议 ≥8 GB；调整 `MAX_ASYNC`/`ENTITY_EXTRACT_CONCURRENCY`/`POSTGRES_HNSW_M`/`POSTGRES_HNSW_EF` |
| embedding 维度不一致 | `EMBEDDING_MODEL`/`EMBEDDING_DIM` 必须与知识库既有向量身份一致，改模型需重建索引 |