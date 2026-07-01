"""
版权审核流程 — 版权状态标记、审核状态机。

状态流转: PENDING → IN_REVIEW → AUTHORIZED / REJECTED
数据存储: PostgreSQL ``copyright_audit_log`` 表（唯一后端）
"""

import logging
from datetime import datetime

from ..knowledge_graph.models import CopyrightStatus, ResourceMetadata

logger = logging.getLogger(__name__)


async def _pg_pool():
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


class CopyrightReviewer:
    """版权审核流程管理器 — PG-backed."""

    # 合法状态转换
    VALID_TRANSITIONS = {
        CopyrightStatus.PENDING: [CopyrightStatus.IN_REVIEW],
        CopyrightStatus.IN_REVIEW: [CopyrightStatus.AUTHORIZED, CopyrightStatus.REJECTED],
        CopyrightStatus.AUTHORIZED: [],  # 终态
        CopyrightStatus.REJECTED: [CopyrightStatus.PENDING],  # 可重新提交
    }

    def __init__(self):
        pass  # PG-backed — no local file path needed

    async def submit_for_review(self, resource: ResourceMetadata,
                          submitter: str = "") -> dict:
        """提交资源进行版权审核。

        Returns:
            {"success": bool, "new_status": str, "message": str}
        """
        if resource.copyright_status != CopyrightStatus.PENDING:
            return {
                "success": False,
                "new_status": resource.copyright_status.value,
                "message": f"资源状态为 {resource.copyright_status.value}，不可提交审核",
            }

        resource.copyright_status = CopyrightStatus.IN_REVIEW
        await self._log_event(resource.id, CopyrightStatus.PENDING, CopyrightStatus.IN_REVIEW, submitter, "提交审核")
        return {"success": True, "new_status": "in_review", "message": "已提交审核"}

    async def approve(self, resource: ResourceMetadata,
                reviewer: str = "",
                notes: str = "",
                authorized_scope: str = "") -> dict:
        """审核通过 — 授权使用。"""
        if resource.copyright_status != CopyrightStatus.IN_REVIEW:
            return {
                "success": False,
                "new_status": resource.copyright_status.value,
                "message": f"资源状态为 {resource.copyright_status.value}，不可审批",
            }

        resource.copyright_status = CopyrightStatus.AUTHORIZED
        resource.reviewer_id = reviewer
        resource.review_notes = notes
        resource.authorized_scope = authorized_scope or resource.authorized_scope
        resource.reviewed_at = datetime.now()

        await self._log_event(resource.id, CopyrightStatus.IN_REVIEW, CopyrightStatus.AUTHORIZED, reviewer, notes)
        return {"success": True, "new_status": "authorized", "message": "审核已通过"}

    async def reject(self, resource: ResourceMetadata,
               reviewer: str = "",
               reason: str = "") -> dict:
        """审核拒绝。"""
        if resource.copyright_status != CopyrightStatus.IN_REVIEW:
            return {
                "success": False,
                "new_status": resource.copyright_status.value,
                "message": f"资源状态为 {resource.copyright_status.value}，不可审批",
            }

        resource.copyright_status = CopyrightStatus.REJECTED
        resource.reviewer_id = reviewer
        resource.review_notes = reason
        resource.reviewed_at = datetime.now()

        await self._log_event(resource.id, CopyrightStatus.IN_REVIEW, CopyrightStatus.REJECTED, reviewer, reason)
        return {"success": True, "new_status": "rejected", "message": f"审核已拒绝: {reason}"}

    def get_pending_reviews(self, resources: list[ResourceMetadata]) -> list[ResourceMetadata]:
        """获取所有待审核的资源。"""
        return [r for r in resources if r.copyright_status == CopyrightStatus.IN_REVIEW]

    def get_authorized_resources(self, resources: list[ResourceMetadata]) -> list[ResourceMetadata]:
        """获取所有已授权的资源。"""
        return [r for r in resources if r.copyright_status == CopyrightStatus.AUTHORIZED]

    async def get_audit_trail(self, resource_id: str = "") -> list[dict]:
        """获取审核轨迹。

        Args:
            resource_id: 资源 ID，为空则返回全部
        """
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            if resource_id:
                rows = await conn.fetch(
                    """SELECT resource_id, from_status, to_status, operator,
                              notes, timestamp
                       FROM copyright_audit_log
                       WHERE resource_id = $1
                       ORDER BY created_at DESC""",
                    resource_id,
                )
            else:
                rows = await conn.fetch(
                    """SELECT resource_id, from_status, to_status, operator,
                              notes, timestamp
                       FROM copyright_audit_log
                       ORDER BY created_at DESC""",
                )
        return [dict(r) for r in rows]

    def get_statistics(self, resources: list[ResourceMetadata]) -> dict:
        """版权审核统计。"""
        counts = {"total": len(resources)}
        for status in CopyrightStatus:
            counts[status.value] = sum(
                1 for r in resources if r.copyright_status == status
            )
        return counts

    async def _log_event(self, resource_id: str,
                   from_status: CopyrightStatus,
                   to_status: CopyrightStatus,
                   operator: str, notes: str) -> None:
        """Write audit event to PG."""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO copyright_audit_log
                   (resource_id, from_status, to_status, operator, notes, timestamp)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                resource_id, from_status.value, to_status.value,
                operator, notes, datetime.now(),
            )
