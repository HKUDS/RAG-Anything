"""
多模态知识库构建流水线。

功能：
- 赛题结构化引擎：批量处理 → 结构化 JSON
- 评分标准数字化：规则解析 → 判定条件
- 工艺库/故障案例库：文档入库、分类、检索
- 教材知识点对齐：语义相似度映射
- 资源标注引擎：模态识别 + 统一标注
- 数据清洗流水线 + 版权审核节点
"""

from .exam_structurer import ExamStructurer
from .scoring_digitizer import ScoringDigitizer
from .process_library import ProcessLibrary
from .fault_case_library import FaultCaseLibrary
from .textbook_aligner import TextbookAligner
from .resource_annotator import ResourceAnnotator
from .data_cleaner import DataCleaner
from .copyright_reviewer import CopyrightReviewer

__all__ = [
    "ExamStructurer",
    "ScoringDigitizer",
    "ProcessLibrary",
    "FaultCaseLibrary",
    "TextbookAligner",
    "ResourceAnnotator",
    "DataCleaner",
    "CopyrightReviewer",
]
