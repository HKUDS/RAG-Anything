from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

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

        parser_tab, phase1_tab, phase2_tab, chat_tab = st.tabs(
            [
                "Parser Results",
                "Pipeline Phase 1",
                "Pipeline Phase 2 QA",
                "Manual QA",
            ]
        )

        with parser_tab:
            self._render_parser_results()
        with phase1_tab:
            self._render_pipeline_phase1(selected_exp)
        with phase2_tab:
            self._render_pipeline_phase2(selected_exp)
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


def render_dashboard() -> None:
    WorkbenchDashboard().render()
