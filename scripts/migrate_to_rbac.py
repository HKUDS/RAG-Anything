#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG-Anything 数据库迁移脚本：is_admin 二值模型 → RBAC 五级角色系统

迁移内容：
  1. 创建 roles 表 + 插入 5 个默认角色（super_admin/dept_admin/teacher/assistant/student）
  2. users 表新增 role_id、last_login_at、must_change_password 列
  3. 现有用户数据迁移（is_admin=1 → super_admin, is_admin=0 → student）
  4. 创建 audit_logs 表及索引
  5. 使用事务包裹，失败自动回滚；输出迁移结果统计

用法：
  python scripts/migrate_to_rbac.py [--db-path auth.db] [--dry-run]
"""

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ── 权限常量（与 raganything/permissions.py 保持一致）────────────────

PERMISSIONS = {
    "super_admin": [
        "users:read", "users:write", "users:delete",
        "kb:read", "kb:write", "kb:delete",
        "agent:read", "agent:write", "agent:delete",
        "settings:read", "settings:write",
        "audit:read",
        "monitor:read",
        "analytics:read",
        "workflow:read", "workflow:write",
        "manufacturing:read", "manufacturing:write",
    ],
    "dept_admin": [
        "users:read", "users:write",
        "kb:read", "kb:write", "kb:delete",
        "agent:read", "agent:write", "agent:delete",
        "settings:read", "audit:read", "monitor:read",
        "analytics:read",
        "workflow:read", "workflow:write",
        "manufacturing:read", "manufacturing:write",
    ],
    "teacher": [
        "kb:read", "kb:write",
        "agent:read", "agent:write",
        "monitor:read", "analytics:read",
        "workflow:read",
        "manufacturing:read", "manufacturing:write",
    ],
    "assistant": [
        "kb:read", "kb:write",
        "agent:read",
        "monitor:read",
        "manufacturing:read",
    ],
    "student": [
        "kb:read",
        "agent:read",
        "manufacturing:read",
    ],
}

ROLES = [
    ("super_admin", "超级管理员，拥有全部权限（信息中心/IT运维）"),
    ("dept_admin", "系部管理员，管理系统内知识库、智能体和用户（系主任/实训中心主任）"),
    ("teacher", "主讲教师，可创建管理自有知识库和智能体（任课教师）"),
    ("assistant", "助理教师，可编辑知识库内容、使用智能体（实训指导教师/助教）"),
    ("student", "学生，可查看知识库并使用智能体问答（各年级学生）"),
]


def migrate(db_path: str, dry_run: bool = False) -> dict:
    """执行 RBAC 迁移，返回统计信息。"""
    stats = {
        "roles_created": 0,
        "columns_added": 0,
        "users_migrated": 0,
        "tables_created": 0,
        "errors": [],
    }

    # 检查数据库是否存在
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"❌ 数据库文件不存在: {db_path}")
        sys.exit(1)

    # 备份
    if not dry_run:
        backup_path = db_file.with_suffix(f".backup-{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"📦 已备份数据库到: {backup_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        if dry_run:
            print("🔍 DRY RUN 模式 — 不会实际修改数据库\n")

        # ── Step 1: 创建 roles 表 ──
        print("📋 Step 1: 创建 roles 表...")
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS roles (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT UNIQUE NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    permissions TEXT NOT NULL DEFAULT '[]',
                    created_at  TEXT DEFAULT (datetime('now','localtime'))
                )
            """)

        # 插入默认角色
        import json as _json
        for role_name, role_desc in ROLES:
            perms_json = _json.dumps(PERMISSIONS.get(role_name, []))
            existing = conn.execute(
                "SELECT id FROM roles WHERE name = ?", (role_name,)
            ).fetchone()
            if not existing:
                if not dry_run:
                    conn.execute(
                        "INSERT INTO roles (name, description, permissions) VALUES (?, ?, ?)",
                        (role_name, role_desc, perms_json),
                    )
                stats["roles_created"] += 1
                print(f"  ✅ 角色已创建: {role_name}")
            else:
                print(f"  ⏭️  角色已存在，跳过: {role_name}")

        # ── Step 2: users 表新增列 ──
        print("\n📋 Step 2: users 表新增列...")
        new_columns = [
            ("role_id", "INTEGER REFERENCES roles(id) DEFAULT NULL"),
            ("last_login_at", "TEXT DEFAULT NULL"),
            ("must_change_password", "INTEGER DEFAULT 0"),
        ]
        # 获取现有列名
        existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        for col_name, col_def in new_columns:
            if col_name not in existing_cols:
                if not dry_run:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
                stats["columns_added"] += 1
                print(f"  ✅ 列已添加: users.{col_name}")
            else:
                print(f"  ⏭️  列已存在，跳过: users.{col_name}")

        # ── Step 3: 现有用户数据迁移 ──
        print("\n📋 Step 3: 迁移现有用户数据...")
        # 获取角色 ID（优先查找新角色名，回退到旧角色名）
        super_admin_role = (
            conn.execute("SELECT id FROM roles WHERE name = 'super_admin'").fetchone()
            or conn.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()
        )
        student_role = (
            conn.execute("SELECT id FROM roles WHERE name = 'student'").fetchone()
            or conn.execute("SELECT id FROM roles WHERE name = 'viewer'").fetchone()
        )

        if not super_admin_role or not student_role:
            raise RuntimeError("角色数据不完整（缺少 super_admin/admin 或 student/viewer），迁移中止")

        admin_role_id = super_admin_role["id"]
        student_role_id = student_role["id"]

        users = conn.execute("SELECT id, username, is_admin FROM users").fetchall()
        for user in users:
            new_role_id = admin_role_id if user["is_admin"] else student_role_id
            existing_role = conn.execute(
                "SELECT role_id FROM users WHERE id = ?", (user["id"],)
            ).fetchone()
            if existing_role["role_id"] is None:
                if not dry_run:
                    conn.execute(
                        "UPDATE users SET role_id = ? WHERE id = ?",
                        (new_role_id, user["id"]),
                    )
                stats["users_migrated"] += 1
                role_label = "super_admin" if user["is_admin"] else "student"
                print(f"  ✅ {user['username']} → {role_label}")

        if stats["users_migrated"] == 0:
            print("  ℹ️  所有用户已有角色分配，无需迁移")

        # ── Step 4: 创建 audit_logs 表 ──
        print("\n📋 Step 4: 创建 audit_logs 表...")
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_id        INTEGER NOT NULL REFERENCES users(id),
                    action          TEXT NOT NULL,
                    target_user_id  INTEGER REFERENCES users(id),
                    details         TEXT NOT NULL DEFAULT '{}',
                    ip_address      TEXT DEFAULT NULL,
                    created_at      TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            # 索引
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_actor
                ON audit_logs(actor_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_action
                ON audit_logs(action)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_created
                ON audit_logs(created_at)
            """)
        stats["tables_created"] += 1
        print("  ✅ audit_logs 表及索引已创建")

        # ── 提交 ──
        if not dry_run:
            conn.commit()
            print("\n🎉 迁移成功完成！")
        else:
            conn.rollback()
            print("\n🔍 DRY RUN 完成 — 未修改数据库")

    except Exception as e:
        conn.rollback()
        stats["errors"].append(str(e))
        print(f"\n❌ 迁移失败: {e}")
        print("🔄 数据库已回滚到迁移前状态")
        if not dry_run:
            print(f"💡 如需恢复，请使用备份文件")
        raise
    finally:
        conn.close()

    return stats


def print_summary(stats: dict, dry_run: bool):
    """打印迁移汇总。"""
    mode = "DRY RUN" if dry_run else "实际迁移"
    print(f"\n{'='*50}")
    print(f"  迁移汇总 ({mode})")
    print(f"{'='*50}")
    print(f"  角色创建:     {stats['roles_created']} 个")
    print(f"  列添加:       {stats['columns_added']} 列")
    print(f"  用户迁移:     {stats['users_migrated']} 个")
    print(f"  表创建:       {stats['tables_created']} 个")
    if stats["errors"]:
        print(f"  错误:         {len(stats['errors'])} 个")
        for err in stats["errors"]:
            print(f"    - {err}")
    print(f"{'='*50}")


def main():
    parser = argparse.ArgumentParser(description="RAG-Anything RBAC 数据库迁移脚本")
    parser.add_argument(
        "--db-path",
        default="./auth.db",
        help="auth.db 路径 (默认: ./auth.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅检查不实际修改",
    )
    args = parser.parse_args()

    print(f"🗄️  数据库: {args.db_path}")
    print(f"🕐 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    try:
        stats = migrate(args.db_path, dry_run=args.dry_run)
        print_summary(stats, dry_run=args.dry_run)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
