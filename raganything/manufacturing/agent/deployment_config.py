"""
定制化部署配置 — 知识库范围选择、回答风格参数、访问权限控制。

数据存储: PostgreSQL ``institution_configs`` 表 + 内存缓存（唯一后端）
"""

import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


async def _pg_pool():
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


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
    """多机构部署配置管理器 — PG-backed with in-memory cache."""

    def __init__(self):
        self._configs: dict[str, InstitutionConfig] = {}
        self._loaded: bool = False

    async def initialize(self) -> None:
        """Load all institution configs from PG into memory cache."""
        if self._loaded:
            return
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT institution_id, institution_name, institution_type,
                          enabled_tracks, enabled_knowledge_types,
                          answer_style, citation_style, language,
                          max_concurrent_users, rate_limit_per_minute,
                          allow_code_parser, allow_video_locator, allow_fault_diagnosis,
                          theme, custom_logo_url
                   FROM institution_configs""",
            )
        for row in rows:
            r = dict(row)
            # Parse JSONB fields
            for jsonb_field in ("enabled_tracks", "enabled_knowledge_types"):
                if isinstance(r[jsonb_field], str):
                    import json
                    try:
                        r[jsonb_field] = json.loads(r[jsonb_field])
                    except Exception:
                        r[jsonb_field] = []
            self._configs[r["institution_id"]] = InstitutionConfig(**r)
        self._loaded = True
        logger.info("已从 PG 加载 %d 个机构配置", len(self._configs))

    # ── Read methods (sync — from in-memory cache) ──────

    def get_config(self, institution_id: str) -> Optional[InstitutionConfig]:
        """获取机构配置。"""
        return self._configs.get(institution_id)

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

    # ── Write methods (async — PG + cache) ──────────────

    async def register_institution(self, config: InstitutionConfig) -> str:
        """注册新的院校/企业配置。"""
        self._configs[config.institution_id] = config
        await self._save_one(config.institution_id)
        return config.institution_id

    async def update_config(self, institution_id: str,
                      updates: dict) -> bool:
        """更新机构配置。"""
        config = self._configs.get(institution_id)
        if not config:
            return False
        for key, value in updates.items():
            if hasattr(config, key):
                setattr(config, key, value)
        await self._save_one(institution_id)
        return True

    async def remove_institution(self, institution_id: str) -> bool:
        """移除机构配置。"""
        if institution_id in self._configs:
            del self._configs[institution_id]
            pool = await _pg_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM institution_configs WHERE institution_id = $1",
                    institution_id,
                )
            return True
        return False

    # ── Internal ────────────────────────────────────────

    async def _save_one(self, institution_id: str) -> None:
        """Write one institution config to PG (upsert)."""
        config = self._configs.get(institution_id)
        if not config:
            return
        import json
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO institution_configs
                   (institution_id, institution_name, institution_type,
                    enabled_tracks, enabled_knowledge_types,
                    answer_style, citation_style, language,
                    max_concurrent_users, rate_limit_per_minute,
                    allow_code_parser, allow_video_locator, allow_fault_diagnosis,
                    theme, custom_logo_url)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                   ON CONFLICT (institution_id) DO UPDATE SET
                    institution_name = EXCLUDED.institution_name,
                    institution_type = EXCLUDED.institution_type,
                    enabled_tracks = EXCLUDED.enabled_tracks,
                    enabled_knowledge_types = EXCLUDED.enabled_knowledge_types,
                    answer_style = EXCLUDED.answer_style,
                    citation_style = EXCLUDED.citation_style,
                    language = EXCLUDED.language,
                    max_concurrent_users = EXCLUDED.max_concurrent_users,
                    rate_limit_per_minute = EXCLUDED.rate_limit_per_minute,
                    allow_code_parser = EXCLUDED.allow_code_parser,
                    allow_video_locator = EXCLUDED.allow_video_locator,
                    allow_fault_diagnosis = EXCLUDED.allow_fault_diagnosis,
                    theme = EXCLUDED.theme,
                    custom_logo_url = EXCLUDED.custom_logo_url,
                    updated_at = NOW()""",
                config.institution_id, config.institution_name, config.institution_type,
                json.dumps(config.enabled_tracks, ensure_ascii=False),
                json.dumps(config.enabled_knowledge_types, ensure_ascii=False),
                config.answer_style, config.citation_style, config.language,
                config.max_concurrent_users, config.rate_limit_per_minute,
                config.allow_code_parser, config.allow_video_locator, config.allow_fault_diagnosis,
                config.theme, config.custom_logo_url,
            )
