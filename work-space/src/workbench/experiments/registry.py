from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, Mapping

from src.workbench.experiments.base import (
    ParserBenchmarkExperimentDefinition,
    PipelineExperimentDefinition,
    PruningExperimentDefinition,
    PostprocessingExperimentDefinition,
    RetrievalExperimentDefinition,
)


@dataclass(frozen=True)
class ExperimentSuite:
    parser: Mapping[str, ParserBenchmarkExperimentDefinition]
    pipeline: Mapping[str, PipelineExperimentDefinition]
    retrieval: Mapping[str, RetrievalExperimentDefinition]
    pruning: Mapping[str, PruningExperimentDefinition]
    postprocessing: Mapping[str, PostprocessingExperimentDefinition]

    @property
    def all(self) -> Dict[str, object]:
        experiments: Dict[str, object] = {}
        experiments.update(self.parser)
        experiments.update(self.pipeline)
        experiments.update(self.retrieval)
        experiments.update(self.pruning)
        experiments.update(self.postprocessing)
        return experiments

    def get(self, experiment_id: str):
        return self.all.get(experiment_id)

    def ids(self) -> Iterable[str]:
        return self.all.keys()

    def items(self) -> Iterator[tuple[str, object]]:
        return self.all.items()
