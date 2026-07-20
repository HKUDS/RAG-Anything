#!/usr/bin/env python3
"""
PostgreSQL 一键初始化脚本
- 创建数据库
- 运行 schema 迁移
- 配置 .env

用法:
  python scripts/pg_setup.py --password <你的postgres密码>

或交互式:
  python scripts/pg_setup.py
"""

import argparse
import getpass
import os
import sys
import subprocess
from pathlib import Path


def find_psql() -> str:
    """Find psql.exe on this system."""
    candidates = [
        "psql",
        r"D:\PostgreSQL\bin\psql.exe",
        r"C:\Program Files\PostgreSQL\16\bin\psql.exe",
        r"D:\Program Files\PostgreSQL\16\bin\psql.exe",
    ]
    for p in candidates:
        try:
            result = subprocess.run([p, "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return p
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
    print("[错误] 找不到 psql.exe，确认 PostgreSQL 已安装")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="RAG-Anything PostgreSQL 初始化")
    parser.add_argument("--password", help="postgres 用户密码")
    parser.add_argument("--db-name", default="raganything", help="数据库名")
    parser.add_argument("--db-user", default="raganything", help="应用数据库用户")
    parser.add_argument("--db-password", help="应用数据库用户密码（默认同 --password）")
    args = parser.parse_args()

    password = args.password or os.getenv("PGPASSWORD") or getpass.getpass("postgres 用户密码: ")
    db_password = args.db_password or password

    ROOT = Path(__file__).resolve().parent.parent
    migration_files = [
        ROOT / "migrations" / "001_pg_schema.sql",
        ROOT / "migrations" / "013_monitor_events.sql",
        ROOT / "migrations" / "016_knowledge_chunk_tags.sql",
        ROOT / "migrations" / "017_automatic_tag_assignments.sql",
    ]
    env_file = ROOT / ".env"

    for migration_file in migration_files:
        if not migration_file.exists():
            print(f"[错误] Schema 文件不存在: {migration_file}")
            sys.exit(1)

    psql = find_psql()
    print(f"[OK] 找到 psql: {psql}")

    env = os.environ.copy()
    env["PGPASSWORD"] = password

    def run_sql(sql: str, db: str = "postgres", desc: str = ""):
        """Execute SQL via psql."""
        print(f"  {desc} ...", end=" ", flush=True)
        cmd = [psql, "-U", "postgres", "-d", db, "-c", sql]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        if result.returncode == 0:
            print("OK")
        elif "already exists" in result.stderr.lower():
            print("已存在，跳过")
        elif "does not exist" in result.stderr.lower():
            print("已跳过（无需操作）")
        else:
            print(f"失败: {result.stderr.strip()[:200]}")
            if "password authentication failed" in result.stderr.lower():
                print("[错误] 密码不正确，请重试")
                sys.exit(1)

    print("\n--- 1. 创建数据库 ---")
    run_sql(
        f"CREATE DATABASE {args.db_name} OWNER postgres;",
        desc=f"创建数据库 {args.db_name}",
    )

    print("\n--- 2. 创建应用用户 ---")
    run_sql(
        f"CREATE USER {args.db_user} WITH PASSWORD '{db_password}';",
        desc=f"创建用户 {args.db_user}",
    )
    run_sql(
        f"GRANT ALL ON DATABASE {args.db_name} TO {args.db_user};",
        desc=f"授权 {args.db_user} 访问 {args.db_name}",
    )

    print("\n--- 3. 运行 Schema 迁移 ---")
    env["PGPASSWORD"] = db_password
    for migration_file in migration_files:
        print(f"  -> 执行 {migration_file.name}")
        cmd = [psql, "-U", args.db_user, "-d", args.db_name, "-f", str(migration_file)]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        if result.returncode == 0:
            print(f"     [OK] {migration_file.name} 执行完成")
            continue

        error_msg = result.stderr.strip()
        if "already exists" in error_msg.lower():
            print(f"     [OK] {migration_file.name} 已存在，跳过")
            continue

        print(f"     [失败] {error_msg[:300]}")
        print("     可能需要先授权 schema 权限:")
        env["PGPASSWORD"] = password
        grant_sql = f"GRANT ALL ON SCHEMA public TO {args.db_user}; ALTER SCHEMA public OWNER TO {args.db_user};"
        subprocess.run(
            [psql, "-U", "postgres", "-d", args.db_name, "-c", grant_sql],
            capture_output=True, text=True, env=env, timeout=30,
        )
        env["PGPASSWORD"] = db_password
        result2 = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        if result2.returncode == 0:
            print(f"     [OK] {migration_file.name} 执行完成（授权后重试）")
        else:
            print(f"     [失败] {result2.stderr.strip()[:300]}")

    print("\n--- 4. 配置 .env ---")
    dsn = f"postgresql://{args.db_user}:{db_password}@localhost:5432/{args.db_name}"
    env_lines = []
    if env_file.exists():
        env_lines = env_file.read_text(encoding="utf-8").splitlines()

    # 移除旧的 DATABASE_URL 行，添加新的
    new_lines = []
    replaced = False
    for line in env_lines:
        if line.startswith("DATABASE_URL=") or line.startswith("# DATABASE_URL="):
            if not replaced:
                new_lines.append(f"DATABASE_URL={dsn}")
                replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append("")
        new_lines.append(f"# PostgreSQL 连接")
        new_lines.append(f"DATABASE_URL={dsn}")

    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"  [OK] DATABASE_URL 已写入 {env_file}")

    print("\n" + "=" * 50)
    print("  PostgreSQL 初始化完成！")
    print(f"  数据库: {args.db_name}")
    print(f"  用户:   {args.db_user}")
    print(f"  DSN:    {dsn}")
    print("=" * 50)
    print("\n  现在启动服务器: python server.py -w 4")


if __name__ == "__main__":
    main()
