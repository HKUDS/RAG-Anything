from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    title: str
    description: str
    category: str
    hardware_sensitive: bool = False
    higher_is_better: bool = True
    primary: bool = False


@dataclass(frozen=True)
class MetricPlan:
    summary: str
    metrics: List[MetricDefinition] = field(default_factory=list)
    insight_questions: List[str] = field(default_factory=list)


@dataclass
class ResultEnvelope:
    experiment_id: str
    file_name: str
    status: str
    metrics: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    notes: Optional[str] = None
