from src.workbench.experiments.parser.definitions import PARSER_EXPERIMENTS
from src.workbench.experiments.pipeline.definitions import PIPELINE_EXPERIMENTS
from src.workbench.experiments.pruning.definitions import PRUNING_EXPERIMENTS
from src.workbench.experiments.postprocessing.definitions import POSTPROCESSING_EXPERIMENTS
from src.workbench.experiments.registry import ExperimentSuite
from src.workbench.experiments.retrieval.definitions import RETRIEVAL_EXPERIMENTS

EXPERIMENT_SUITE = ExperimentSuite(
    parser=PARSER_EXPERIMENTS,
    pipeline=PIPELINE_EXPERIMENTS,
    retrieval=RETRIEVAL_EXPERIMENTS,
    pruning=PRUNING_EXPERIMENTS,
    postprocessing=POSTPROCESSING_EXPERIMENTS,
)

ALL_EXPERIMENTS = EXPERIMENT_SUITE.all

__all__ = [
    "EXPERIMENT_SUITE",
    "ALL_EXPERIMENTS",
    "PARSER_EXPERIMENTS",
    "PIPELINE_EXPERIMENTS",
    "RETRIEVAL_EXPERIMENTS",
    "PRUNING_EXPERIMENTS",
    "POSTPROCESSING_EXPERIMENTS",
]
