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

    def __init__(self, process_library=None, fault_case_library=None,
                 deployment_config=None):
        self.process_library = process_library
        self.fault_case_library = fault_case_library
        self.deployment_config = deployment_config

    def adapt(self, enterprise_id: str, enterprise_name: str,
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
            self.deployment_config.register_institution(config)

        # 导入工艺文档
        if process_docs_dir and self.process_library:
            try:
                doc_dir = Path(process_docs_dir)
                for doc_file in doc_dir.glob("*"):
                    try:
                        self.process_library.ingest_document(doc_file)
                        result["process_docs_imported"] += 1
                    except Exception as e:
                        result["errors"].append(f"工艺文档 {doc_file.name}: {e}")
            except Exception as e:
                result["errors"].append(f"工艺库导入失败: {e}")

        # 导入故障案例
        if fault_data_dir and self.fault_case_library:
            try:
                data_dir = Path(fault_data_dir)
                for json_file in data_dir.glob("*.json"):
                    try:
                        cases_data = json.loads(json_file.read_text(encoding="utf-8"))
                        if isinstance(cases_data, dict):
                            cases_data = [cases_data]
                        for case_data in cases_data:
                            from ..knowledge_graph.models import FaultCase
                            case = FaultCase(**case_data)
                            self.fault_case_library.add_case(case)
                            result["fault_cases_imported"] += 1
                    except Exception as e:
                        result["errors"].append(f"故障案例 {json_file.name}: {e}")
            except Exception as e:
                result["errors"].append(f"故障案例库导入失败: {e}")

        return result

    def validate_adaptation(self, enterprise_id: str) -> dict:
        """验证企业场景适配效果。

        检查项：数据完整性、检索可用性、配置正确性。
        """
        issues = []
        warnings = []

        # 检查工艺库
        if self.process_library:
            stats = self.process_library.list_by_category()
            if not stats:
                issues.append("工艺库为空 — 未导入任何工艺文档")

        # 检查故障案例库
        if self.fault_case_library:
            case_stats = self.fault_case_library.get_statistics()
            if case_stats["total_cases"] < 5:
                warnings.append(f"故障案例仅 {case_stats['total_cases']} 条，建议至少 20 条")
        else:
            issues.append("故障案例库未初始化")

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
