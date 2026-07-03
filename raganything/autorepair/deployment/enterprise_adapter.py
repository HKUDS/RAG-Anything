"""
企业场景适配工具。
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class EnterpriseAdapter:
    """企业场景适配器。"""

    def __init__(self, case_library=None, deployment_config=None):
        self.case_library = case_library
        self.deployment_config = deployment_config

    async def adapt(self, enterprise_id: str, enterprise_name: str,
              process_docs_dir: str = "",
              fault_data_dir: str = "") -> dict:
        """适配企业场景。

        Args:
            enterprise_id: 企业 ID
            enterprise_name: 企业名称
            process_docs_dir: 工艺文档目录
            fault_data_dir: 故障案例数据目录

        Returns:
            适配结果
        """
        result = {
            "enterprise_id": enterprise_id,
            "enterprise_name": enterprise_name,
            "process_docs_imported": 0,
            "fault_cases_imported": 0,
            "errors": [],
            "adapted_at": datetime.now().isoformat(),
        }

        # 注册企业配置
        if self.deployment_config:
            from ..agent.deployment_config import InstitutionConfig
            config = InstitutionConfig(
                institution_id=enterprise_id,
                institution_name=enterprise_name,
                institution_type="enterprise",
            )
            await self.deployment_config.register_institution(config)

        # 导入工艺文档
        if process_docs_dir and self.case_library:
            try:
                doc_dir = Path(process_docs_dir)
                for doc_file in doc_dir.glob("*"):
                    try:
                        from ..knowledge_graph.models import Case
                        text = doc_file.read_text(encoding="utf-8")
                        case = Case(
                            id=f"proc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{doc_file.stem}",
                            title=doc_file.stem,
                            case_type="process",
                            full_text=text,
                            text_preview=text[:500],
                            file_path=str(doc_file.absolute()),
                            file_size_bytes=doc_file.stat().st_size,
                        )
                        await self.case_library.add_case(case)
                        result["process_docs_imported"] += 1
                    except Exception as e:
                        result["errors"].append(f"工艺文档 {doc_file.name}: {e}")
            except Exception as e:
                result["errors"].append(f"工艺库导入失败: {e}")

        # 导入故障案例
        if fault_data_dir and self.case_library:
            try:
                data_dir = Path(fault_data_dir)
                for json_file in data_dir.glob("*.json"):
                    try:
                        cases_data = json.loads(json_file.read_text(encoding="utf-8"))
                        if isinstance(cases_data, dict):
                            cases_data = [cases_data]
                        for case_data in cases_data:
                            from ..knowledge_graph.models import Case
                            case_data["case_type"] = "fault"
                            case = Case(**{k: v for k, v in case_data.items()
                                           if k in Case.__dataclass_fields__})
                            await self.case_library.add_case(case)
                            result["fault_cases_imported"] += 1
                    except Exception as e:
                        result["errors"].append(f"故障案例 {json_file.name}: {e}")
            except Exception as e:
                result["errors"].append(f"故障案例库导入失败: {e}")

        return result

    async def validate_adaptation(self, enterprise_id: str) -> dict:
        """验证企业场景适配效果。

        检查项：数据完整性、检索可用性、配置正确性。
        """
        issues = []
        warnings = []

        # 检查统一案例库
        if self.case_library:
            all_stats = await self.case_library.get_statistics()
            proc_total = all_stats.get("process_total", 0)
            fault_total = all_stats.get("fault_total", 0)
            if proc_total == 0:
                issues.append("工艺案例为空 — 未导入任何工艺文档")
            if fault_total < 5:
                warnings.append(f"故障案例仅 {fault_total} 条，建议至少 20 条")
        else:
            issues.append("案例库未初始化")

        # 检查配置
        if self.deployment_config:
            config = self.deployment_config.get_config(enterprise_id)
            if not config:
                issues.append(f"企业 {enterprise_id} 配置未注册")

        return {
            "enterprise_id": enterprise_id,
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "validated_at": datetime.now().isoformat(),
        }
