"""
定制化部署配置 — 知识库范围选择、回答风格参数、访问权限控制。
"""

import json
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class InstitutionConfig:
    """院校/企业级别的部署配置。"""
    institution_id: str
    institution_name: str
    institution_type: str = "school"  # "school" / "enterprise"

    # 知识库范围
    enabled_tracks: list[str] = field(default_factory=list)  # 启用的赛项
    enabled_knowledge_types: list[str] = field(default_factory=lambda: [
        "exams", "scoring", "processes", "fault_cases", "textbooks", "videos"
    ])

    # 智能体行为
    answer_style: str = "detailed"  # "concise" / "detailed" / "teaching"
    citation_style: str = "inline"  # "inline" / "footnote"
    language: str = "zh-CN"

    # 访问控制
    max_concurrent_users: int = 50
    rate_limit_per_minute: int = 30
    allow_code_parser: bool = True
    allow_video_locator: bool = True
    allow_fault_diagnosis: bool = True

    # 外观
    theme: str = "default"
    custom_logo_url: str = ""


class DeploymentConfig:
    """多机构部署配置管理器。"""

    def __init__(self, config_path: str | Path = "./config/deployments.json"):
        self.config_path = Path(config_path)
        self._configs: dict[str, InstitutionConfig] = {}
        self._load()

    def register_institution(self, config: InstitutionConfig) -> str:
        """注册新的院校/企业配置。"""
        self._configs[config.institution_id] = config
        self._save()
        return config.institution_id

    def get_config(self, institution_id: str) -> Optional[InstitutionConfig]:
        """获取机构配置。"""
        return self._configs.get(institution_id)

    def update_config(self, institution_id: str,
                      updates: dict) -> bool:
        """更新机构配置。"""
        config = self._configs.get(institution_id)
        if not config:
            return False
        for key, value in updates.items():
            if hasattr(config, key):
                setattr(config, key, value)
        self._save()
        return True

    def remove_institution(self, institution_id: str) -> bool:
        """移除机构配置。"""
        if institution_id in self._configs:
            del self._configs[institution_id]
            self._save()
            return True
        return False

    def list_institutions(self) -> list[dict]:
        """列出所有注册机构。"""
        return [
            {
                "id": c.institution_id,
                "name": c.institution_name,
                "type": c.institution_type,
                "enabled_tracks": c.enabled_tracks,
            }
            for c in self._configs.values()
        ]

    def get_knowledge_scope(self, institution_id: str) -> Optional[dict]:
        """获取机构的知识库访问范围。"""
        config = self._configs.get(institution_id)
        if not config:
            return None
        return {
            "enabled_tracks": config.enabled_tracks,
            "enabled_knowledge_types": config.enabled_knowledge_types,
        }

    def check_access(self, institution_id: str,
                     feature: str) -> bool:
        """检查机构是否有权使用某项功能。"""
        config = self._configs.get(institution_id)
        if not config:
            return False
        feature_flags = {
            "code_parser": config.allow_code_parser,
            "video_locator": config.allow_video_locator,
            "fault_diagnosis": config.allow_fault_diagnosis,
        }
        return feature_flags.get(feature, False)

    def _save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for iid, config in self._configs.items():
            data[iid] = {
                "institution_id": config.institution_id,
                "institution_name": config.institution_name,
                "institution_type": config.institution_type,
                "enabled_tracks": config.enabled_tracks,
                "enabled_knowledge_types": config.enabled_knowledge_types,
                "answer_style": config.answer_style,
                "citation_style": config.citation_style,
                "language": config.language,
                "max_concurrent_users": config.max_concurrent_users,
                "rate_limit_per_minute": config.rate_limit_per_minute,
                "allow_code_parser": config.allow_code_parser,
                "allow_video_locator": config.allow_video_locator,
                "allow_fault_diagnosis": config.allow_fault_diagnosis,
                "theme": config.theme,
                "custom_logo_url": config.custom_logo_url,
            }
        self.config_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> None:
        if self.config_path.exists():
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            for iid, cfg in data.items():
                self._configs[iid] = InstitutionConfig(**cfg)
