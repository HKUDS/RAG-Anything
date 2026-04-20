from __future__ import annotations

from src.workbench.experiments.base import PipelineExperimentDefinition
from src.workbench.experiments.pipeline.profiles import PIPELINE_PROFILES
from src.workbench.experiments.shared import PARSER_PRESETS
from src.workbench.metrics import PIPELINE_METRIC_PLAN
from src.config import ENV

PIPELINE_EXPERIMENTS: dict[str, PipelineExperimentDefinition] = {}

default_profile = PIPELINE_PROFILES["default"]
medical_profile = PIPELINE_PROFILES["medical"]
mineru_local_preset = PARSER_PRESETS["mineru"]
mineru_cloud_preset = PARSER_PRESETS["mineru_cloud_vlm"]
shared_input_dir = "./datasets/parser_benchmark/raw_docs"

PIPELINE_EXPERIMENTS["exp1_baseline_mineru_cloud_openai"] = PipelineExperimentDefinition(
    id="exp1_baseline_mineru_cloud_openai",
    description="Baseline end-to-end smoke test using MinerU official cloud parsing and OpenAI models.",
    category="pipeline",
    metric_plan=PIPELINE_METRIC_PLAN,
    profile_name="default",
    provider="openai",
    parser=mineru_cloud_preset.parser,
    parse_method=mineru_cloud_preset.parse_method,
    input_dir_override=shared_input_dir,
    parser_kwargs=dict(mineru_cloud_preset.parser_kwargs),
    use_gliner=default_profile.use_gliner,
    gliner_labels=list(default_profile.gliner_labels),
    lightrag_kwargs=dict(default_profile.lightrag_kwargs),
    raganything_kwargs=dict(default_profile.raganything_kwargs),
    custom_prompts=dict(default_profile.custom_prompts),
    notes=(
        "Reference deployment-style baseline for partners: official MinerU Precision API + OpenAI. "
        "Useful for comparing environment/runtime overhead against local parser runs."
    ),
    tags=["pipeline", "baseline", "mineru_cloud", "openai"],
)

PIPELINE_EXPERIMENTS["exp2_default_mineru_ollama"] = PipelineExperimentDefinition(
    id="exp2_default_mineru_ollama",
    description="Default pipeline using local MinerU parser and Ollama-compatible models.",
    category="pipeline",
    metric_plan=PIPELINE_METRIC_PLAN,
    profile_name="default",
    provider="ollama",
    parser=mineru_local_preset.parser,
    parse_method=mineru_local_preset.parse_method,
    input_dir_override=shared_input_dir,
    parser_kwargs=dict(mineru_local_preset.parser_kwargs),
    use_gliner=default_profile.use_gliner,
    gliner_labels=list(default_profile.gliner_labels),
    lightrag_kwargs=dict(default_profile.lightrag_kwargs),
    raganything_kwargs=dict(default_profile.raganything_kwargs),
    custom_prompts=dict(default_profile.custom_prompts),
    notes="Local default pipeline baseline using MinerU + Ollama-compatible serving.",
    tags=["pipeline", "default", "mineru", "ollama"],
)

PIPELINE_EXPERIMENTS["exp4_medical_scope_mineru_ollama"] = PipelineExperimentDefinition(
    id="exp4_medical_scope_mineru_ollama",
    description="Medical-domain pipeline using local MinerU parser and Ollama-compatible models.",
    category="pipeline",
    metric_plan=PIPELINE_METRIC_PLAN,
    profile_name="medical",
    provider="ollama",
    parser=mineru_local_preset.parser,
    parse_method=mineru_local_preset.parse_method,
    input_dir_override=shared_input_dir,
    parser_kwargs=dict(mineru_local_preset.parser_kwargs),
    use_gliner=medical_profile.use_gliner,
    gliner_labels=list(medical_profile.gliner_labels),
    lightrag_kwargs=dict(medical_profile.lightrag_kwargs),
    raganything_kwargs=dict(medical_profile.raganything_kwargs),
    custom_prompts=dict(medical_profile.custom_prompts),
    notes=(
        "Medical-domain prompt shaping over the default pipeline. "
        "Prompt overrides live in `work-space/src/prompts/medical.py` and are wired in "
        "`work-space/src/workbench/experiments/pipeline/profiles.py`."
    ),
    tags=["pipeline", "medical", "mineru", "ollama"],
)

PIPELINE_EXPERIMENTS["exp5_medical_scope_mineru_ollama_radgraph_xl"] = PipelineExperimentDefinition(
    id="exp5_medical_scope_mineru_ollama_radgraph_xl",
    description=(
        "Medical-domain pipeline using MinerU cloud parsing and RadGraph-XL for "
        "entity/relation extraction over textified multimodal chunks."
    ),
    category="pipeline",
    metric_plan=PIPELINE_METRIC_PLAN,
    profile_name="medical",
    provider="ollama",
    parser=mineru_cloud_preset.parser,
    parse_method=mineru_cloud_preset.parse_method,
    input_dir_override=shared_input_dir,
    parser_kwargs=dict(mineru_cloud_preset.parser_kwargs),
    entity_relation_backend="radgraph_xl",
    entity_relation_kwargs={
        "model_type": ENV.radgraph_model_type,
        "batch_size": ENV.radgraph_batch_size,
        "cuda_device": ENV.radgraph_cuda_device,
        "split_chunks": ENV.radgraph_split_chunks,
        "max_segment_chars": ENV.radgraph_max_segment_chars,
        "sentence_overlap": ENV.radgraph_sentence_overlap,
        "empty_cache_each_batch": ENV.radgraph_empty_cache_each_batch,
    },
    use_gliner=medical_profile.use_gliner,
    gliner_labels=list(medical_profile.gliner_labels),
    lightrag_kwargs=dict(medical_profile.lightrag_kwargs),
    raganything_kwargs=dict(medical_profile.raganything_kwargs),
    custom_prompts=dict(medical_profile.custom_prompts),
    notes=(
        "Variant-2 NER/RE experiment: keep current MinerU multimodal-to-text flow, "
        "but replace LightRAG LLM extraction with RadGraph-XL on the final text chunks."
    ),
    tags=["pipeline", "medical", "mineru_cloud", "ollama", "radgraph_xl", "ner"],
)
