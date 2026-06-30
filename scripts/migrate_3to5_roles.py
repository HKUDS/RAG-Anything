#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG-Anything 角色升级脚本：3角色 → 5角色体系

适用场景：已有数据库使用 admin/editor/viewer 三角色体系，需升级到五角色体系。

迁移内容：
  1. 自动备份数据库（.backup-{timestamp}）
  2. 插入 5 个新角色（super_admin/dept_admin/teacher/assistant/student）
  3. 旧角色名映射到新角色（admin→super_admin, editor→teacher, viewer→student）
  4. 用户角色 ID 更新（仅更新仍指向旧角色的用户）
  5. 旧角色可选保留或删除（--remove-old）
  6. 使用事务包裹，失败自动回滚

用法：
  # 预览（不实际修改）
  python scripts/migrate_3to5_roles.py --dry-run

  # 执行升级（保留旧角色作为别名）
  python scripts/migrate_3to5_roles.py

  # 执行升级 + 删除旧角色
  python scripts/migrate_3to5_roles.py --remove-old

  # 指定数据库路径
  python scripts/migrate_3to5_roles.py --db-path ./auth.db
"""

import argparse
import json as _json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ── 五级角色定义 ─────────────────────────────────────────────

NEW_ROLES = [
    (
        "super_admin",
        "超级管理员，拥有全部权限（信息中心/IT运维）",
        [
            "users:read", "users:write", "users:delete",
            "kb:read", "kb:write", "kb:delete",
            "agent:read", "agent:write", "agent:delete",
            "settings:read", "settings:write",
            "audit:read", "monitor:read",
            "analytics:read",
            "workflow:read", "workflow:write",
            "manufacturing:read", "manufacturing:write",
        ],
    ),
    (
        "dept_admin",
        "系部管理员，管理系统内知识库、智能体和用户（系主任/实训中心主任）",
        [
            "users:read", "users:write",
            "kb:read", "kb:write", "kb:delete",
            "agent:read", "agent:write", "agent:delete",
            "settings:read", "audit:read", "monitor:read",
            "analytics:read",
            "workflow:read", "workflow:write",
            "manufacturing:read", "manufacturing:write",
        ],
    ),
    (
        "teacher",
        "主讲教师，可创建管理自有知识库和智能体（任课教师）",
        [
            "kb:read", "kb:write",
            "agent:read", "agent:write",
            "monitor:read", "analytics:read",
            "workflow:read",
            "manufacturing:read", "manufacturing:write",
        ],
    ),
    (
        "assistant",
        "助理教师，可编辑知识库内容、使用智能体（实训指导教师/助教）",
        [
            "kb:read", "kb:write",
            "agent:read",
            "monitor:read",
            "manufacturing:read",
        ],
    ),
    (
        "student",
        "学生，可查看知识库并使用智能体问答（各年级学生）",
        [
            "kb:read",
            "agent:read",
            "manufacturing:read",
        ],
    ),
]

# 旧角色 → 新角色映射（用于用户迁移）
ROLE_REMAP = {
    "admin": "super_admin",
    "editor": "teacher",
    "viewer": "student",
}


def detect_old_roles(conn: sqlite3.Connection) -> dict:
    """检测数据库中存在的旧角色，返回 {old_name: role_row}。"""
    old_roles = {}
    for old_name in ROLE_REMAP:
        row = conn.execute(
            "SELECT id, name FROM roles WHERE name = ?", (old_name,)
        ).fetchone()
        if row:
            old_roles[old_name] = dict(row)
    return old_roles


def detect_new_roles(conn: sqlite3.Connection) -> dict:
    """检测数据库中已存在的新角色，返回 {new_name: role_row}。"""
    new_roles = {}
    for role_name, _, _ in NEW_ROLES:
        row = conn.execute(
            "SELECT id, name FROM roles WHERE name = ?", (role_name,)
        ).fetchone()
        if row:
            new_roles[role_name] = dict(row)
    return new_roles


def migrate(db_path: str, dry_run: bool = False, remove_old: bool = False) -> dict:
    """执行 3→5 角色升级迁移。"""
    stats = {
        "roles_inserted": 0,
        "roles_skipped": 0,
        "users_remapped": 0,
        "old_roles_removed": 0,
        "errors": [],
    }

    db_file = Path(db_path)
    if not db_file.exists():
        print(f"❌ 数据库文件不存在: {db_path}")
        sys.exit(1)

    # ── 备份 ──
    if not dry_run:
        backup_path = db_file.with_suffix(
            f".backup-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        shutil.copy2(db_path, backup_path)
        print(f"📦 已备份数据库到: {backup_path}\n")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        if dry_run:
            print("🔍 DRY RUN 模式 — 不会实际修改数据库\n")

        # ── 检查前提条件 ──
        # 确保 roles 表存在
        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='roles'"
        ).fetchone()
        if not table_check:
            raise RuntimeError("roles 表不存在，请先运行 migrate_to_rbac.py 初始化 RBAC 系统")

        # ── Step 1: 检测现有角色 ──
        print("📋 Step 1: 检测现有角色...")
        old_roles = detect_old_roles(conn)
        existing_new = detect_new_roles(conn)

        if old_roles:
            print(f"  发现旧角色: {', '.join(old_roles.keys())}")
        else:
            print("  ℹ️  未发现旧角色（可能已是五角色系统）")

        if existing_new:
            print(f"  已存在新角色: {', '.join(existing_new.keys())}")

        # ── Step 2: 插入新角色 ──
        print("\n📋 Step 2: 插入新角色...")
        for role_name, role_desc, role_perms in NEW_ROLES:
            if role_name in existing_new:
                print(f"  ⏭️  角色已存在，跳过: {role_name}")
                stats["roles_skipped"] += 1
                continue

            perms_json = _json.dumps(role_perms)
            if not dry_run:
                conn.execute(
                    "INSERT INTO roles (name, description, permissions) VALUES (?, ?, ?)",
                    (role_name, role_desc, perms_json),
                )
            stats["roles_inserted"] += 1
            print(f"  ✅ 角色已创建: {role_name} — {role_desc}")

        if stats["roles_inserted"] == 0 and stats["roles_skipped"] > 0:
            print("  ℹ️  所有新角色已存在，跳过插入")

        # ── Step 3: 用户角色映射 ──
        print("\n📋 Step 3: 用户角色映射 (旧→新)...")
        if not old_roles:
            print("  ℹ️  无旧角色需要映射，跳过")
        else:
            # 重新读取（Step 2 可能刚插入了新角色）
            new_roles_map = detect_new_roles(conn)

            # 构建名称→名称映射（用于 dry-run 显示）
            name_mapping = {old: new for old, new in ROLE_REMAP.items()}

            # 构建 ID 映射: old_role_id → new_role_id
            id_mapping = {}
            for old_name, new_name in ROLE_REMAP.items():
                if old_name not in old_roles:
                    continue
                old_id = old_roles[old_name]["id"]
                if new_name in new_roles_map:
                    # 新角色已存在 → 直接映射 ID
                    id_mapping[old_id] = new_roles_map[new_name]["id"]
                elif dry_run:
                    # DRY RUN: 新角色尚未创建，使用旧角色 ID 模拟（实际运行时会正确映射）
                    id_mapping[old_id] = old_id
                else:
                    print(f"  ⚠️  新角色 '{new_name}' 未找到，跳过映射旧角色 '{old_name}' 的用户")

            if not id_mapping:
                print("  ⚠️  无法构建角色 ID 映射，跳过用户迁移")
            else:
                # 查询指向旧角色的用户
                old_ids = tuple(id_mapping.keys())
                placeholders = ",".join("?" * len(old_ids))
                users_to_remap = conn.execute(
                    f"SELECT id, username, role_id FROM users WHERE role_id IN ({placeholders})",
                    old_ids,
                ).fetchall()

                for user in users_to_remap:
                    old_id = user["role_id"]
                    # 根据 old_id 反查旧角色名，再映射到新角色名
                    old_name = next(
                        (n for n, r in old_roles.items() if r["id"] == old_id), None
                    )
                    new_name = name_mapping.get(old_name, "?") if old_name else "?"

                    if not dry_run:
                        new_role_id = id_mapping[old_id]
                        conn.execute(
                            "UPDATE users SET role_id = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                            (new_role_id, user["id"]),
                        )
                    stats["users_remapped"] += 1
                    print(f"  ✅ {user['username']} ({old_name}) → {new_name}")

                if stats["users_remapped"] == 0:
                    print("  ℹ️  无用户需要映射，所有用户已使用新角色")

        # ── Step 4: 可选删除旧角色 ──
        if remove_old and old_roles:
            print("\n📋 Step 4: 删除旧角色 (--remove-old)...")
            for old_name in old_roles:
                # 安全检查：确保没有用户仍指向此角色
                old_id = old_roles[old_name]["id"]
                remaining = conn.execute(
                    "SELECT COUNT(*) as cnt FROM users WHERE role_id = ?", (old_id,)
                ).fetchone()
                if remaining["cnt"] > 0:
                    print(f"  ⚠️  跳过 {old_name}: 仍有 {remaining['cnt']} 个用户使用此角色")
                    continue
                if not dry_run:
                    conn.execute("DELETE FROM roles WHERE id = ?", (old_id,))
                stats["old_roles_removed"] += 1
                print(f"  ✅ 旧角色已删除: {old_name}")
        elif remove_old and not old_roles:
            print("\n📋 Step 4: 删除旧角色 — 无旧角色可删除")

        # ── 提交 ──
        if not dry_run:
            conn.commit()
            print("\n🎉 角色升级成功完成！")
        else:
            conn.rollback()
            print("\n🔍 DRY RUN 完成 — 未修改数据库")

    except Exception as e:
        conn.rollback()
        stats["errors"].append(str(e))
        print(f"\n❌ 升级失败: {e}")
        print("🔄 数据库已回滚到升级前状态")
        if not dry_run:
            print(f"💡 如需恢复，请使用备份文件: {db_file.with_suffix('')}.backup-*")
        raise
    finally:
        conn.close()

    return stats


def print_summary(stats: dict, dry_run: bool):
    """打印升级汇总。"""
    mode = "DRY RUN" if dry_run else "实际升级"
    print(f"\n{'='*55}")
    print(f"  角色升级汇总 ({mode})")
    print(f"{'='*55}")
    print(f"  新角色插入:   {stats['roles_inserted']} 个")
    print(f"  角色已存在:   {stats['roles_skipped']} 个")
    print(f"  用户已映射:   {stats['users_remapped']} 个")
    print(f"  旧角色删除:   {stats['old_roles_removed']} 个")
    if stats["errors"]:
        print(f"  错误:         {len(stats['errors'])} 个")
        for err in stats["errors"]:
            print(f"    - {err}")
    print(f"{'='*55}")


def main():
    parser = argparse.ArgumentParser(
        description="RAG-Anything 3角色→5角色升级脚本"
    )
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
    parser.add_argument(
        "--remove-old",
        action="store_true",
        help="升级后删除旧角色 (admin/editor/viewer)，仅在无用户使用时删除",
    )
    args = parser.parse_args()

    print(f"🗄️  数据库: {args.db_path}")
    print(f"🕐 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.remove_old:
        print(f"🗑️  模式: 升级后删除旧角色")
    print()

    try:
        stats = migrate(args.db_path, dry_run=args.dry_run, remove_old=args.remove_old)
        print_summary(stats, dry_run=args.dry_run)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
