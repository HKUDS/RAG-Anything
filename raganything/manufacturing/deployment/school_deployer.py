"""
院校试点部署工具。
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class SchoolDeployer:
    """院校试点部署管理器。"""

    def __init__(self, deployment_config=None):
        self.deployment_config = deployment_config
        self._deployments: dict[str, dict] = {}
        self._feedback: dict[str, list[dict]] = {}

    def deploy(self, school_id: str, school_name: str,
               tracks: list[str] | None = None) -> dict:
        """部署到试点院校。

        Returns:
            部署状态
        """
        deployment = {
            "school_id": school_id,
            "school_name": school_name,
            "tracks": tracks or [],
            "status": "deploying",
            "deployed_at": datetime.now().isoformat(),
            "health": "pending",
        }

        try:
            # 注册机构配置
            if self.deployment_config:
                from ..agent.deployment_config import InstitutionConfig
                config = InstitutionConfig(
                    institution_id=school_id,
                    institution_name=school_name,
                    institution_type="school",
                    enabled_tracks=tracks or [],
                )
                self.deployment_config.register_institution(config)

            deployment["status"] = "active"
            deployment["health"] = "healthy"
        except Exception as e:
            deployment["status"] = "failed"
            deployment["error"] = str(e)

        self._deployments[school_id] = deployment
        return deployment

    def collect_feedback(self, school_id: str,
                         user_id: str,
                         query: str,
                         rating: int,
                         comment: str = "") -> dict:
        """收集用户反馈。

        Args:
            school_id: 院校 ID
            user_id: 用户 ID
            query: 用户查询
            rating: 评分 1-5
            comment: 评语

        Returns:
            反馈记录
        """
        feedback = {
            "school_id": school_id,
            "user_id": user_id,
            "query": query,
            "rating": rating,
            "comment": comment,
            "timestamp": datetime.now().isoformat(),
        }

        if school_id not in self._feedback:
            self._feedback[school_id] = []
        self._feedback[school_id].append(feedback)

        return feedback

    def get_feedback_summary(self, school_id: str = "") -> dict:
        """获取反馈汇总。

        Args:
            school_id: 院校 ID，为空则汇总全部
        """
        feedbacks = []
        if school_id:
            feedbacks = self._feedback.get(school_id, [])
        else:
            for fb_list in self._feedback.values():
                feedbacks.extend(fb_list)

        if not feedbacks:
            return {"total": 0, "avg_rating": 0, "distribution": {}}

        ratings = [f["rating"] for f in feedbacks]
        distribution = {}
        for r in ratings:
            distribution[str(r)] = distribution.get(str(r), 0) + 1

        return {
            "total": len(feedbacks),
            "avg_rating": round(sum(ratings) / len(ratings), 2),
            "distribution": distribution,
            "recent_feedback": feedbacks[-10:],
        }

    def generate_pilot_report(self, school_id: str) -> dict:
        """生成试点测试报告。"""
        deployment = self._deployments.get(school_id, {})
        feedback_summary = self.get_feedback_summary(school_id)

        return {
            "school_id": school_id,
            "school_name": deployment.get("school_name", ""),
            "deployment_status": deployment.get("status", "unknown"),
            "deployed_at": deployment.get("deployed_at", ""),
            "feedback": feedback_summary,
            "recommendations": self._generate_recommendations(feedback_summary),
            "generated_at": datetime.now().isoformat(),
        }

    def _generate_recommendations(self, feedback_summary: dict) -> list[str]:
        """基于反馈数据生成改进建议。"""
        recs = []
        avg = feedback_summary.get("avg_rating", 0)
        total = feedback_summary.get("total", 0)

        if total < 10:
            recs.append("样本量不足，建议延长试点周期")
        if avg < 3.0:
            recs.append("用户满意度偏低，建议优先排查核心问答准确率")
        if avg < 4.0 and avg >= 3.0:
            recs.append("用户满意度中等，建议优化回答完整性和响应速度")
        if avg >= 4.0:
            recs.append("用户满意度良好，可准备正式上线")

        return recs
