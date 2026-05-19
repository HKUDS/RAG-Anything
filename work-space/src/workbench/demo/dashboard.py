from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.config import ENV
from src.workbench.experiments.pipeline.definitions import PIPELINE_EXPERIMENTS
from src.workbench.query import RAGQueryEngine


class ReportRepository:
    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.reports_dir = self.output_root / "reports"

    @property
    def parser_summary_path(self) -> Path:
        return self.reports_dir / "parser_benchmark_summary.csv"

    @property
    def pipeline_phase1_path(self) -> Path:
        return self.reports_dir / "pipeline_benchmark.csv"

    @property
    def pipeline_phase2_summary_path(self) -> Path:
        return self.reports_dir / "pipeline_qa_summary.csv"

    @property
    def pipeline_phase2_detail_path(self) -> Path:
        return self.reports_dir / "pipeline_qa_details.jsonl"

    @property
    def retrieval_summary_path(self) -> Path:
        return self.reports_dir / "retrieval_benchmark_summary.csv"

    @property
    def retrieval_detail_path(self) -> Path:
        return self.reports_dir / "retrieval_benchmark_details.jsonl"

    @property
    def pruning_summary_path(self) -> Path:
        return self.reports_dir / "pruning_benchmark_summary.csv"

    @property
    def pruning_detail_path(self) -> Path:
        return self.reports_dir / "pruning_benchmark_details.jsonl"

    def load_csv(self, path: Path) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        try:
            return pd.read_csv(path)
        except Exception:
            return self._load_csv_tolerant(path)

    @staticmethod
    def _load_csv_tolerant(path: Path) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return pd.DataFrame()
                expected_len = len(header)
                for row in reader:
                    if len(row) != expected_len:
                        continue
                    rows.append(dict(zip(header, row)))
        except Exception:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    def load_jsonl(self, path: Path) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        rows: list[dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return pd.DataFrame(rows)

    def load_parser_summary(self) -> pd.DataFrame:
        return self.load_csv(self.parser_summary_path)

    def load_pipeline_phase1(self) -> pd.DataFrame:
        return self.load_csv(self.pipeline_phase1_path)

    def load_pipeline_phase2_summary(self) -> pd.DataFrame:
        return self.load_csv(self.pipeline_phase2_summary_path)

    def load_pipeline_phase2_details(self) -> pd.DataFrame:
        return self.load_jsonl(self.pipeline_phase2_detail_path)

    def load_retrieval_summary(self) -> pd.DataFrame:
        return self.load_csv(self.retrieval_summary_path)

    def load_retrieval_details(self) -> pd.DataFrame:
        return self.load_jsonl(self.retrieval_detail_path)

    def load_pruning_summary(self) -> pd.DataFrame:
        return self.load_csv(self.pruning_summary_path)

    def load_pruning_details(self) -> pd.DataFrame:
        return self.load_jsonl(self.pruning_detail_path)

    def list_available_pipeline_experiments(self) -> list[str]:
        defined = [
            exp_id
            for exp_id, exp_def in PIPELINE_EXPERIMENTS.items()
            if not getattr(exp_def, "legacy_alias", False)
        ]
        available = []
        for exp_id in defined:
            storage_dir = self.output_root / exp_id / "rag_storage"
            if storage_dir.exists():
                available.append(exp_id)
        return available or defined


class ChatHistoryStore:
    STATE_KEY = "manual_qa_history_by_experiment"

    def __init__(self):
        if self.STATE_KEY not in st.session_state:
            st.session_state[self.STATE_KEY] = {}

    def get(self, experiment_id: str) -> list[dict[str, Any]]:
        history = st.session_state[self.STATE_KEY]
        history.setdefault(experiment_id, [])
        return history[experiment_id]

    def append(self, experiment_id: str, message: dict[str, Any]) -> None:
        self.get(experiment_id).append(message)

    def clear(self, experiment_id: str) -> None:
        st.session_state[self.STATE_KEY][experiment_id] = []


class ManualQAService:
    async def ask(self, experiment_id: str, question: str, mode: str) -> dict[str, Any]:
        engine = RAGQueryEngine(experiment_id)
        await engine.initialize()
        try:
            return await engine.query_with_trace(question, mode=mode)
        finally:
            engine.close()

    def ask_sync(self, experiment_id: str, question: str, mode: str) -> dict[str, Any]:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self.ask(experiment_id, question, mode))
        finally:
            asyncio.set_event_loop(None)
            loop.close()


class WorkbenchDashboard:
    def __init__(self):
        self.repo = ReportRepository(Path(ENV.output_base_dir))
        self.chat_store = ChatHistoryStore()
        self.qa_service = ManualQAService()

    def render(self) -> None:
        st.set_page_config(
            page_title="RAG-Anything Workbench",
            page_icon="RAG",
            layout="wide",
            initial_sidebar_state="expanded",
        )

        selected_exp, query_mode = self._render_sidebar()

        parser_tab, phase1_tab, phase2_tab, retrieval_tab, pruning_tab, chat_tab = st.tabs(
            [
                "Parser Results",
                "Pipeline Phase 1",
                "Pipeline Phase 2 QA",
                "Retrieval Results",
                "Graph Pruning",
                "Manual QA",
            ]
        )

        with parser_tab:
            self._render_parser_results()
        with phase1_tab:
            self._render_pipeline_phase1(selected_exp)
        with phase2_tab:
            self._render_pipeline_phase2(selected_exp)
        with retrieval_tab:
            self._render_retrieval_results(selected_exp)
        with pruning_tab:
            self._render_pruning_results(selected_exp)
        with chat_tab:
            self._render_manual_qa(selected_exp, query_mode)

    def _render_sidebar(self) -> tuple[str | None, str]:
        st.sidebar.title("Workbench")
        experiments = self.repo.list_available_pipeline_experiments()
        selected_exp = None
        if experiments:
            selected_exp = st.sidebar.selectbox(
                "Pipeline Experiment",
                experiments,
                index=len(experiments) - 1,
            )
        else:
            st.sidebar.warning("No pipeline experiments available yet.")

        query_mode = st.sidebar.selectbox(
            "Query Mode",
            ["mix", "naive", "local", "global", "hybrid"],
            index=0,
        )

        if selected_exp:
            st.sidebar.caption(f"Selected: `{selected_exp}`")
            if st.sidebar.button("Clear Chat History", use_container_width=True):
                self.chat_store.clear(selected_exp)
                st.rerun()
        st.sidebar.divider()
        st.sidebar.caption(f"Ollama: `{ENV.ollama_llm}`")
        st.sidebar.caption(f"OpenAI: `{ENV.openai_llm}`")
        return selected_exp, query_mode

    def _render_parser_results(self) -> None:
        st.subheader("Parser Benchmark Summary")
        parser_df = self.repo.load_parser_summary()
        if parser_df.empty:
            st.info("Parser benchmark summary not found.")
            return

        st.dataframe(parser_df.astype(str), use_container_width=True, hide_index=True)
        numeric_df = parser_df.copy()
        for col in ["Parse_Success_Rate", "Median_Sec_Per_Page", "Median_Noise_Ratio", "Median_Tokens_Per_Page"]:
            if col in numeric_df.columns:
                numeric_df[col] = pd.to_numeric(numeric_df[col], errors="coerce")

        chart_cols = [c for c in ["Median_Sec_Per_Page", "Median_Noise_Ratio", "Median_Tokens_Per_Page"] if c in numeric_df.columns]
        if chart_cols:
            chart_df = numeric_df[["Experiment_ID", *chart_cols]].set_index("Experiment_ID")
            st.bar_chart(chart_df)

    def _render_pipeline_phase1(self, selected_exp: str | None) -> None:
        st.subheader("Pipeline Benchmark Phase 1")
        phase1_df = self.repo.load_pipeline_phase1()
        if phase1_df.empty:
            st.info("Pipeline phase 1 report not found.")
            return

        st.dataframe(phase1_df.astype(str), use_container_width=True, hide_index=True)

        if not selected_exp:
            return
        selected_rows = phase1_df[phase1_df["Experiment_ID"] == selected_exp]
        if selected_rows.empty:
            st.info("No phase 1 row for selected experiment.")
            return

        row = selected_rows.iloc[-1]
        col1, col2, col3 = st.columns(3)
        col1.metric("Sec / Page", row.get("End_to_End_Sec_Per_Page", ""))
        col2.metric("Tokens / Page", row.get("Output_Tokens_Per_Page", ""))
        col3.metric("API Calls", row.get("API_Calls", ""))
        st.caption(f"Graph Expansion: {row.get('Graph_Expansion_Profile', '')}")
        st.caption(f"Multimodal Retention: {row.get('Multimodal_Retention_Profile', '')}")

    def _render_pipeline_phase2(self, selected_exp: str | None) -> None:
        st.subheader("Pipeline Benchmark Phase 2 QA")
        summary_df = self.repo.load_pipeline_phase2_summary()
        detail_df = self.repo.load_pipeline_phase2_details()

        if summary_df.empty:
            st.info("Pipeline QA summary not found.")
            return

        st.dataframe(summary_df.astype(str), use_container_width=True, hide_index=True)

        numeric_summary = summary_df.copy()
        for col in [
            "Evidence_Recall_at_10",
            "Correctness",
            "Groundedness",
            "Completeness",
            "Unsupported_Claim_Rate",
            "Final_QA_Score",
        ]:
            if col in numeric_summary.columns:
                numeric_summary[col] = pd.to_numeric(numeric_summary[col], errors="coerce")
        if "Final_QA_Score" in numeric_summary.columns:
            chart_df = numeric_summary[["Experiment_ID", "Final_QA_Score", "Evidence_Recall_at_10"]].set_index("Experiment_ID")
            st.bar_chart(chart_df)

        if not selected_exp or detail_df.empty:
            return

        selected_summary = summary_df[summary_df["Experiment_ID"] == selected_exp]
        if not selected_summary.empty:
            row = selected_summary.iloc[-1]
            c1, c2, c3 = st.columns(3)
            c1.metric("Final QA Score", row.get("Final_QA_Score", ""))
            c2.metric("Evidence Recall@10", row.get("Evidence_Recall_at_10", ""))
            c3.metric("Unsupported Claim Rate", row.get("Unsupported_Claim_Rate", ""))

        selected_details = detail_df[detail_df["experiment_id"] == selected_exp].copy()
        if selected_details.empty:
            return

        visible_cols = [
            "question_id",
            "difficulty",
            "question_type",
            "question",
            "correctness",
            "groundedness",
            "completeness",
            "evidence_recall_at_10",
            "unsupported_claim",
            "judge_cache_hit",
        ]
        visible_cols = [c for c in visible_cols if c in selected_details.columns]
        st.dataframe(selected_details[visible_cols].astype(str), use_container_width=True, hide_index=True)

    def _render_retrieval_results(self, selected_exp: str | None) -> None:
        st.subheader("Retrieval Benchmark")
        summary_df = self.repo.load_retrieval_summary()
        detail_df = self.repo.load_retrieval_details()

        if summary_df.empty:
            st.info("Retrieval benchmark summary not found.")
            return

        st.dataframe(summary_df.astype(str), use_container_width=True, hide_index=True)

        numeric_summary = summary_df.copy()
        for col in ["Evidence_Recall_at_5", "Evidence_Recall_at_10", "MRR", "Precision_at_5"]:
            if col in numeric_summary.columns:
                numeric_summary[col] = pd.to_numeric(numeric_summary[col], errors="coerce")

        if "Retrieval_Experiment_ID" in numeric_summary.columns:
            chart_cols = [c for c in ["MRR", "Precision_at_5", "Evidence_Recall_at_10"] if c in numeric_summary.columns]
            if chart_cols:
                chart_df = numeric_summary[["Retrieval_Experiment_ID", *chart_cols]].set_index("Retrieval_Experiment_ID")
                st.bar_chart(chart_df)

        if not selected_exp:
            return

        selected_summary = summary_df[summary_df["Base_Experiment_ID"] == selected_exp].copy()
        if selected_summary.empty:
            st.info("No retrieval rows for selected experiment.")
            return

        st.markdown(f"**Selected Base Experiment:** `{selected_exp}`")
        st.dataframe(selected_summary.astype(str), use_container_width=True, hide_index=True)

        mode_options = sorted(selected_summary["Query_Mode"].dropna().unique().tolist())
        selected_mode = st.selectbox(
            "Retrieval Query Mode",
            mode_options,
            key=f"retrieval_mode_{selected_exp}",
        )

        mode_summary = selected_summary[selected_summary["Query_Mode"] == selected_mode].copy()
        if not mode_summary.empty:
            mode_summary["Reranker"] = mode_summary["Retrieval_Experiment_ID"].apply(
                lambda value: "bge-reranker-v2-m3" if "bge_reranker_v2_m3" in str(value) else "none"
            )
            comparison_cols = ["Reranker", "MRR", "Precision_at_5", "Evidence_Recall_at_10", "Evidence_Recall_at_5"]
            available_comparison_cols = [c for c in comparison_cols if c in mode_summary.columns]
            st.markdown(f"**Mode Comparison:** `{selected_mode}`")
            st.dataframe(mode_summary[available_comparison_cols].astype(str), use_container_width=True, hide_index=True)

        if detail_df.empty:
            return

        selected_detail = detail_df[
            (detail_df["base_experiment_id"] == selected_exp) & (detail_df["query_mode"] == selected_mode)
        ].copy()
        if selected_detail.empty:
            return

        detail_experiment_ids = sorted(selected_detail["retrieval_experiment_id"].dropna().unique().tolist())
        selected_retrieval_exp = st.selectbox(
            "Retrieval Experiment Detail",
            detail_experiment_ids,
            key=f"retrieval_exp_detail_{selected_exp}_{selected_mode}",
        )
        selected_detail = selected_detail[selected_detail["retrieval_experiment_id"] == selected_retrieval_exp].copy()

        visible_cols = [
            "question_id",
            "difficulty",
            "question_type",
            "question",
            "evidence_recall_at_5",
            "evidence_recall_at_10",
            "mrr",
            "precision_at_5",
            "reranker_name",
            "total_retrieved_chunks",
        ]
        visible_cols = [c for c in visible_cols if c in selected_detail.columns]
        st.dataframe(selected_detail[visible_cols].astype(str), use_container_width=True, hide_index=True)

    def _render_pruning_results(self, selected_exp: str | None) -> None:
        st.subheader("Graph Pruning Benchmark")
        summary_df = self.repo.load_pruning_summary()
        if summary_df.empty:
            st.info("Pruning benchmark summary not found.")
            return

        st.dataframe(summary_df.astype(str), use_container_width=True, hide_index=True)

        numeric_summary = summary_df.copy()
        for col in [
            "Important_Node_Retention",
            "Evidence_Entity_Coverage",
            "Community_Coverage",
            "Noise_Ratio",
            "Chunk_Leakage_Ratio",
            "Connectivity",
            "Merge_Safety",
            "Compression_Gain",
            "Weighted_Score",
        ]:
            if col in numeric_summary.columns:
                numeric_summary[col] = pd.to_numeric(numeric_summary[col], errors="coerce")

        chart_cols = [c for c in ["Weighted_Score", "Evidence_Entity_Coverage", "Important_Node_Retention"] if c in numeric_summary.columns]
        if chart_cols and "Pruning_Experiment_ID" in numeric_summary.columns:
            chart_df = numeric_summary[["Pruning_Experiment_ID", *chart_cols]].set_index("Pruning_Experiment_ID")
            st.bar_chart(chart_df)

        filtered = summary_df.copy()
        if selected_exp:
            filtered = filtered[filtered["Base_Experiment_ID"] == selected_exp]
            if filtered.empty:
                st.info("No pruning rows for selected experiment.")
                return
            st.markdown(f"**Selected Base Experiment:** `{selected_exp}`")

        method_options = sorted(filtered["Pruning_Method"].dropna().unique().tolist())
        selected_method = st.selectbox(
            "Pruning Method",
            method_options,
            key=f"pruning_method_{selected_exp or 'all'}",
        )
        filtered = filtered[filtered["Pruning_Method"] == selected_method].copy()
        st.dataframe(filtered.astype(str), use_container_width=True, hide_index=True)

        pruning_experiment_ids = filtered["Pruning_Experiment_ID"].dropna().unique().tolist()
        selected_pruning_exp = st.selectbox(
            "Pruning Experiment Detail",
            pruning_experiment_ids,
            key=f"pruning_exp_detail_{selected_exp or 'all'}_{selected_method}",
        )
        selected_row = filtered[filtered["Pruning_Experiment_ID"] == selected_pruning_exp].iloc[-1]

        c1, c2, c3 = st.columns(3)
        c1.metric("Weighted Score", selected_row.get("Weighted_Score", ""))
        c2.metric("Important Retention", selected_row.get("Important_Node_Retention", ""))
        c3.metric("Evidence Coverage", selected_row.get("Evidence_Entity_Coverage", ""))
        st.caption(
            " | ".join(
                [
                    f"Connectivity=`{selected_row.get('Connectivity', '')}`",
                    f"Noise=`{selected_row.get('Noise_Ratio', '')}`",
                    f"Chunk Leakage=`{selected_row.get('Chunk_Leakage_Ratio', '')}`",
                    f"Compression Gain=`{selected_row.get('Compression_Gain', '')}`",
                ]
            )
        )

        metadata = self._load_json_path(selected_row.get("Artifact_Metadata_Path", ""))

        if metadata:
            selected_nodes = metadata.get("selected_display_nodes", [])
            if selected_nodes:
                nodes_df = pd.DataFrame(selected_nodes)
                nodes_df = self._sort_pruning_nodes(nodes_df)
                preferred_cols = [
                    "story_order",
                    "story_role",
                    "chapter_label",
                    "label",
                    "entity_type",
                    "media_type",
                    "media_available",
                    "description",
                    "source_file",
                    "is_virtual_merged",
                    "merged_from",
                    "node_id",
                ]
                visible_cols = [c for c in preferred_cols if c in nodes_df.columns]
                st.markdown("**Selected Nodes**")
                st.dataframe(nodes_df[visible_cols].astype(str), use_container_width=True, hide_index=True)

                node_records = nodes_df.to_dict("records")
                node_options = list(range(len(node_records)))
                selected_node_index = st.selectbox(
                    "Node Metadata",
                    node_options,
                    format_func=lambda idx: self._format_pruning_node_option(node_records[idx]),
                    key=f"pruning_node_meta_{selected_pruning_exp}",
                )
                self._render_pruning_node_detail(node_records[selected_node_index])

            merge_groups = metadata.get("merge_groups", [])
            if merge_groups:
                st.markdown("**Virtual Merge Groups**")
                st.dataframe(pd.DataFrame(merge_groups).astype(str), use_container_width=True, hide_index=True)

            debug_info = metadata.get("debug_info", {})
            if debug_info:
                with st.expander("Selection Debug Info", expanded=False):
                    st.json(debug_info)

            llm_response = metadata.get("llm_response")
            if llm_response:
                with st.expander("LLM Selection Response", expanded=False):
                    st.json(llm_response)

        html_content = self._load_html_path(selected_row.get("Artifact_HTML_Path", ""))
        if html_content:
            st.markdown("**Interactive Graph**")
            components.html(html_content, height=760, scrolling=True)
        else:
            st.info("Interactive pruning graph artifact not found.")

    @staticmethod
    def _sort_pruning_nodes(nodes_df: pd.DataFrame) -> pd.DataFrame:
        nodes_df = nodes_df.copy()
        if "story_order" in nodes_df.columns:
            nodes_df["_story_order_num"] = pd.to_numeric(nodes_df["story_order"], errors="coerce").fillna(999999)
            sort_cols = ["_story_order_num"]
            if "label" in nodes_df.columns:
                sort_cols.append("label")
            nodes_df = nodes_df.sort_values(sort_cols).drop(columns=["_story_order_num"])
        elif "label" in nodes_df.columns:
            nodes_df = nodes_df.sort_values("label")
        return nodes_df

    @staticmethod
    def _format_pruning_node_option(record: dict[str, Any]) -> str:
        label = str(record.get("label") or record.get("node_id") or "node")
        entity_type = str(record.get("entity_type") or "entity")
        order = record.get("story_order")
        media_type = str(record.get("media_type") or "")
        try:
            prefix = f"#{int(float(order))} "
        except Exception:
            prefix = ""
        suffix = f" | {media_type}" if media_type else ""
        return f"{prefix}{label} [{entity_type}]{suffix}"

    def _render_pruning_node_detail(self, record: dict[str, Any]) -> None:
        st.markdown("**Node Detail**")
        left, right = st.columns([0.58, 0.42])
        with left:
            detail_fields = [
                "label",
                "entity_type",
                "story_role",
                "chapter_label",
                "why_selected",
                "source_file",
                "source_id",
                "media_type",
                "media_path",
            ]
            details = {
                key: record.get(key, "")
                for key in detail_fields
                if str(record.get(key, "")).strip()
            }
            if details:
                st.json(details, expanded=False)
            description = str(record.get("description") or "").strip()
            if description:
                with st.expander("Description", expanded=False):
                    st.markdown(description)
        with right:
            self._render_pruning_node_media(record)

    def _render_pruning_node_media(self, record: dict[str, Any]) -> None:
        media_type = str(record.get("media_type") or "").lower()
        media_path = self._resolve_existing_path(record.get("media_path", ""))
        caption = str(record.get("media_caption") or record.get("label") or "").strip()
        table_body = str(record.get("table_body") or "").strip()
        equation_text = str(record.get("equation_text") or "").strip()

        if media_path and media_path.suffix.lower() in {".apng", ".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}:
            try:
                st.image(str(media_path), caption=caption or None, use_container_width=True)
            except TypeError:
                st.image(str(media_path), caption=caption or None, use_column_width=True)
        elif media_path:
            st.caption(str(media_path))

        if media_type == "table" and table_body:
            st.markdown("**Table**")
            self._render_table_body(table_body)
        elif media_type == "equation" and equation_text:
            st.markdown("**Equation**")
            try:
                st.latex(equation_text)
            except Exception:
                st.code(equation_text)
        elif equation_text:
            st.markdown("**Equation**")
            st.code(equation_text)

    @staticmethod
    def _render_table_body(table_body: str) -> None:
        if "<table" in table_body.lower():
            st.markdown(table_body, unsafe_allow_html=True)
            return
        lines = [line.strip() for line in table_body.splitlines() if line.strip()]
        markdown_table = len(lines) >= 2 and all("|" in line for line in lines[:2])
        if markdown_table:
            st.markdown(table_body)
        else:
            st.code(table_body[:8000], language="html" if "<" in table_body and ">" in table_body else "text")

    @staticmethod
    def _resolve_existing_path(value: Any) -> Path | None:
        raw = str(value or "").strip().strip('"').strip("'")
        if not raw or raw.lower() in {"none", "null", "n/a"}:
            return None
        path = Path(raw)
        candidates = [path]
        if not path.is_absolute():
            candidates.extend([Path.cwd() / path, Path(ENV.output_base_dir) / path])
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _render_manual_qa(self, selected_exp: str | None, query_mode: str) -> None:
        st.subheader("Manual QA Playground")
        if not selected_exp:
            st.info("Select a pipeline experiment from the sidebar.")
            return

        history = self.chat_store.get(selected_exp)
        for message in history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                trace = message.get("trace")
                if message["role"] == "assistant" and trace:
                    self._render_trace(trace)

        prompt = st.chat_input(f"Ask {selected_exp}...")
        if not prompt:
            return

        self.chat_store.append(selected_exp, {"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner(f"Querying {selected_exp}..."):
                trace = self.qa_service.ask_sync(selected_exp, prompt, query_mode)
            answer = str(trace.get("answer", "")).strip()
            st.markdown(answer)
            self._render_trace(trace)
            self.chat_store.append(
                selected_exp,
                {
                    "role": "assistant",
                    "content": answer,
                    "trace": trace,
                },
            )

    @staticmethod
    def _render_trace(trace: dict[str, Any]) -> None:
        retrieved_context = str(trace.get("retrieved_context", "") or "").strip()
        distilled_context = str(trace.get("distilled_context", "") or "").strip()
        fallback_used = bool(trace.get("fallback_used", False))

        meta_parts = [
            f"mode=`{trace.get('mode', '')}`",
            f"fallback=`{fallback_used}`",
        ]
        st.caption(" | ".join(meta_parts))

        if retrieved_context:
            with st.expander("Retrieved Context", expanded=False):
                st.code(retrieved_context)
        if distilled_context and distilled_context != retrieved_context:
            with st.expander("Distilled Context", expanded=False):
                st.code(distilled_context)

    @staticmethod
    def _load_json_path(path_value: Any) -> dict[str, Any] | None:
        raw_value = str(path_value or "").strip()
        if not raw_value:
            return None
        resolved = WorkbenchDashboard._resolve_artifact_path(raw_value)
        if not resolved or not resolved.exists():
            return None
        if resolved.is_dir():
            return None
        try:
            with open(resolved, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def _load_html_path(path_value: Any) -> str | None:
        raw_value = str(path_value or "").strip()
        if not raw_value:
            return None
        resolved = WorkbenchDashboard._resolve_artifact_path(raw_value)
        if not resolved or not resolved.exists():
            return None
        if resolved.is_dir():
            return None
        try:
            return resolved.read_text(encoding="utf-8")
        except Exception:
            return None

    @staticmethod
    def _resolve_artifact_path(path_value: Any) -> Path | None:
        raw_value = str(path_value or "").strip()
        if not raw_value:
            return None
        raw = Path(raw_value)
        candidates = [raw]
        if not raw.is_absolute():
            candidates.append(Path.cwd() / raw)
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0] if candidates else None


def render_dashboard() -> None:
    WorkbenchDashboard().render()
