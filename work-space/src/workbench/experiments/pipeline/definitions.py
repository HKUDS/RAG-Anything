from __future__ import annotations

from src.workbench.experiments.base import PipelineExperimentDefinition
from src.workbench.experiments.pipeline.profiles import PIPELINE_PROFILES
from src.workbench.experiments.shared import PARSER_PRESETS
from src.workbench.metrics import PIPELINE_METRIC_PLAN

PROFILE_PREFIX = {
    "default": "exp1_baseline",
    "medical": "exp4_medical_scope",
    "hybrid_gliner": "exp6_hybrid_gliner",
}

PIPELINE_EXPERIMENTS: dict[str, PipelineExperimentDefinition] = {}

for profile_key, profile in PIPELINE_PROFILES.items():
    prefix = PROFILE_PREFIX[profile_key]
    for parser_key in ["mineru", "docling", "kreuzberg"]:
        preset = PARSER_PRESETS[parser_key]
        exp_id = f"{prefix}_{parser_key}"
        PIPELINE_EXPERIMENTS[exp_id] = PipelineExperimentDefinition(
            id=exp_id,
            description=f"{profile.title} pipeline with {preset.title} parser",
            category="pipeline",
            metric_plan=PIPELINE_METRIC_PLAN,
            profile_name=profile_key,
            provider="ollama",
            parser=preset.parser,
            parse_method=preset.parse_method,
            parser_kwargs=dict(preset.parser_kwargs),
            use_gliner=profile.use_gliner,
            gliner_labels=list(profile.gliner_labels),
            lightrag_kwargs=dict(profile.lightrag_kwargs),
            raganything_kwargs=dict(profile.raganything_kwargs),
            custom_prompts=dict(profile.custom_prompts),
            notes=profile.notes,
            tags=["pipeline", profile_key, parser_key],
        )

for alias, target in {
    "exp4_medical_scope": "exp4_medical_scope_docling",
    "exp6_hybrid_gliner": "exp6_hybrid_gliner_docling",
}.items():
    base = PIPELINE_EXPERIMENTS[target]
    PIPELINE_EXPERIMENTS[alias] = PipelineExperimentDefinition(
        id=alias,
        description=f"Legacy alias -> {target}",
        category="pipeline",
        metric_plan=PIPELINE_METRIC_PLAN,
        profile_name=base.profile_name,
        provider=base.provider,
        parser=base.parser,
        parse_method=base.parse_method,
        parser_kwargs=dict(base.parser_kwargs),
        use_gliner=base.use_gliner,
        gliner_labels=list(base.gliner_labels),
        lightrag_kwargs=dict(base.lightrag_kwargs),
        raganything_kwargs=dict(base.raganything_kwargs),
        custom_prompts=dict(base.custom_prompts),
        notes=f"Legacy compatibility alias pinned to {target} for fair parser provenance.",
        tags=list(base.tags) + ["legacy"],
        legacy_alias=True,
    )
