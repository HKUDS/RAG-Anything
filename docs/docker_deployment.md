# Container usage

Building requires Docker BuildKit. This image runs RAG-Anything scripts as batch jobs. It does not start an HTTP
service. The default command prints the example's help and exits successfully;
Compose deliberately uses `restart: "no"`.

```bash
cp .env.example .env
# Configure your own model endpoint and models in .env.
mkdir -p inputs
docker compose build
docker compose run --rm raganything python examples/raganything_example.py --help
```

The default image uses CPU PyTorch wheels and installs the `all` extra, FFmpeg,
LibreOffice Writer/Calc/Impress, PDF utilities and the native libraries needed by
MinerU/OpenCV and WeasyPrint. First inference still downloads model weights.
GPU use needs compatible PyTorch wheels, drivers and container runtime settings;
changing a Compose GPU reservation alone does not convert the CPU image.
`TORCH_INDEX_URL` is a build argument for selecting a different wheel index.

Compose stores RAG data, parser outputs and model caches in separate named
volumes. Docker initializes these from directories owned by UID 10001 in the
image. Input files are a read-only bind mount at `/app/inputs`. When using custom
bind mounts for writable outputs, arrange host permissions for UID 10001 first.
Removing a job with `--rm` preserves named volumes; `docker compose down -v`
deletes them.

Override the command with your application script, and pass its required model,
embedding dimension, input and output options. `.env.example` is an example
configuration, not a guarantee that a chosen endpoint serves every listed model.
Use `docker compose run --rm` for repeated jobs. `docker compose up` runs the
help command once and stops. Inject real model credentials at runtime.

# 容器使用

构建需要 Docker BuildKit。此镜像用于运行 RAG-Anything 批处理脚本，不会启动 HTTP 服务。默认命令显示示例的
帮助信息后正常退出，因此 Compose 使用 `restart: "no"`，不会反复重启。

先复制 `.env.example` 为 `.env`，配置自己的模型端点和模型，创建 `inputs` 目录，
再执行上面的构建和运行命令。默认安装 CPU 版 PyTorch、`all` 可选依赖、FFmpeg、
LibreOffice Writer/Calc/Impress、PDF 工具，以及 MinerU/OpenCV、WeasyPrint 所需的
系统库。首次推理仍需下载模型权重。GPU 使用还需要匹配的 PyTorch、驱动及容器
运行时配置，仅增加 Compose GPU 声明不足以让 CPU 镜像使用 GPU。

RAG 数据、解析输出及模型缓存分别放在命名卷中，输入文件只读挂载到 `/app/inputs`。
镜像使用 UID 10001；如果自行改成可写的宿主机目录挂载，需要提前设置对应权限。
`--rm` 不会删除命名卷；`docker compose down -v` 会删除卷内数据。

实际处理时，用自己的应用脚本替换默认命令，并传入脚本所需的模型、向量维度、
输入及输出参数。示例环境变量不代表任意端点都提供列出的模型。重复任务使用
`docker compose run --rm`；`docker compose up` 默认只运行一次帮助命令。
真实凭据应在运行时注入，不放进镜像构建上下文。
