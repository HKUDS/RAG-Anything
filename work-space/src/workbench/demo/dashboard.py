from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from src.config import ENV
from src.pruning import GraphVisualizer, PRUNING_ALGORITHMS, PruningBenchmark, list_algorithms
from src.workbench.judging import GeminiEvaluator
from src.workbench.query import RAGQueryEngine


def _load_experiment_dirs(output_path: Path) -> list[str]:
    if not output_path.exists():
        return []
    return sorted([d.name for d in output_path.iterdir() if d.is_dir()])


def _render_sidebar(output_path: Path) -> str | None:
    st.sidebar.title("Experiment Control")
    exp_dirs = _load_experiment_dirs(output_path)
    if not exp_dirs:
        st.sidebar.warning("No experiments found. Run the benchmark scripts first.")
        return None

    selected_exp = st.sidebar.selectbox("Select Experiment", exp_dirs, index=len(exp_dirs) - 1)
    st.sidebar.success(f"Loaded: {selected_exp}")
    st.sidebar.divider()
    st.sidebar.info(f"Default server: {ENV.ollama_base_url}")
    st.sidebar.info(f"Default LLM: {ENV.ollama_llm}")
    return selected_exp


def _render_metrics_tab(selected_exp: str, output_path: Path):
    st.header(f"Experiment Analysis: {selected_exp}")
    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Benchmark Metrics")
        report_path = Path(ENV.report_file)
        if not report_path.exists():
            st.warning("No benchmark report found.")
        else:
            df = pd.read_csv(report_path)
            exp_data = df[df["Experiment_ID"] == selected_exp]
            if exp_data.empty:
                st.warning("Metrics not recorded yet.")
            else:
                display_df = exp_data.T
                display_df.columns = ["Value"]
                st.dataframe(display_df.astype(str), hide_index=False)

    with col2:
        st.subheader("Knowledge Graph Topology")
        algorithm_options = {alg["id"]: alg["name"] for alg in list_algorithms()}
        selected_algorithm = st.selectbox(
            "Pruning Algorithm",
            options=list(algorithm_options.keys()),
            format_func=lambda x: algorithm_options[x],
            index=list(algorithm_options.keys()).index("hybrid"),
        )
        max_nodes = st.slider("Max nodes to display", min_value=20, max_value=300, value=ENV.pruning_max_nodes, step=10)

        if st.button("Generate Interactive Graph", type="primary"):
            storage_dir = output_path / selected_exp / "rag_storage"
            with st.spinner(f"Visualizing with {algorithm_options[selected_algorithm]}..."):
                viz = GraphVisualizer(str(storage_dir))
                html_path = viz.generate_html(max_nodes=max_nodes, algorithm_id=selected_algorithm)
                if not html_path:
                    st.error("Graph file not found.")
                else:
                    with open(html_path, "r", encoding="utf-8") as f:
                        st.components.v1.html(f.read(), height=600, scrolling=True)
                    st.caption(f"Top-{max_nodes} nodes using {algorithm_options[selected_algorithm]}.")


def _render_pruning_tab(selected_exp: str, output_path: Path):
    st.header("Pruning Algorithm Benchmark")
    col1, col2 = st.columns(2)
    with col1:
        benchmark_max_nodes = st.number_input("Max Nodes for Benchmark", min_value=10, max_value=200, value=ENV.pruning_max_nodes)
    with col2:
        enable_llm_eval = st.checkbox("Enable LLM Evaluation", value=False)

    if st.button("Run Benchmark", type="primary", key="run_pruning_benchmark"):
        storage_dir = output_path / selected_exp / "rag_storage"
        viz = GraphVisualizer(str(storage_dir))
        graph = viz.get_full_graph()
        if graph is None:
            st.error("Could not load graph.")
        else:
            with st.spinner("Running benchmark on all algorithms..."):
                benchmark = PruningBenchmark(graph, max_nodes=benchmark_max_nodes)
                results = benchmark.run(PRUNING_ALGORITHMS)
                st.session_state.pruning_results = results
                st.session_state.pruning_summary = benchmark.get_summary()
                benchmark.to_csv(str(Path(ENV.pruning_benchmark_report)))
                st.success("Benchmark complete.")

    if st.session_state.get("pruning_results"):
        results = st.session_state.pruning_results
        best = results[0]
        st.success(f"Recommended: {best.algorithm_name} (Score: {best.weighted_score:.4f})")
        results_data = []
        for result in results:
            results_data.append(
                {
                    "Algorithm": result.algorithm_name,
                    "Nodes": result.actual_nodes,
                    "Edges": result.actual_edges,
                    "Hub Ret.": f"{result.hub_retention:.2%}",
                    "Bridge Ret.": f"{result.bridge_retention:.2%}",
                    "Cluster Cov.": f"{result.cluster_coverage:.2%}",
                    "Connectivity": f"{result.connectivity:.2%}",
                    "LLM Score": f"{result.llm_score:.2f}" if result.llm_score is not None else "N/A",
                    "Total Score": f"{result.weighted_score:.4f}",
                }
            )
        st.dataframe(pd.DataFrame(results_data), hide_index=True, use_container_width=True)
        chart_data = pd.DataFrame(
            {
                "Algorithm": [r.algorithm_name for r in results],
                "Hub Retention": [r.hub_retention for r in results],
                "Bridge Retention": [r.bridge_retention for r in results],
                "Cluster Coverage": [r.cluster_coverage for r in results],
                "Connectivity": [r.connectivity for r in results],
            }
        ).set_index("Algorithm")
        st.bar_chart(chart_data)
        with st.expander("Full Summary"):
            st.code(st.session_state.pruning_summary)


def _render_judge_tab(selected_exp: str, output_path: Path):
    st.header("Automated Evaluation with Gemini")
    gold_dataset_path = Path(ENV.gold_dataset_file)

    if not ENV.google_api_key:
        st.error("Missing GOOGLE_API_KEY in .env file.")
        return

    if "gold_questions" not in st.session_state:
        if gold_dataset_path.exists():
            try:
                with open(gold_dataset_path, "r", encoding="utf-8") as f:
                    st.session_state.gold_questions = json.load(f)
            except Exception:
                st.session_state.gold_questions = []
        else:
            st.session_state.gold_questions = []

    if "eval_results" not in st.session_state:
        st.session_state.eval_results = []

    st.subheader("Step 1: Test Dataset Management")
    col_gen, col_reset = st.columns([1, 4])
    with col_gen:
        btn_label = "Generate New Questions" if not st.session_state.gold_questions else "Regenerate Questions"
        if st.button(btn_label, type="primary" if not st.session_state.gold_questions else "secondary"):
            chunk_file = output_path / selected_exp / "rag_storage" / "kv_store_text_chunks.json"
            if chunk_file.exists():
                with st.spinner("Gemini is reading document to generate QA pairs..."):
                    with open(chunk_file, "r", encoding="utf-8") as f:
                        chunks = json.load(f)
                    context_samples = [chunk["content"] for chunk in list(chunks.values())[:15]]
                    questions = GeminiEvaluator().generate_gold_questions("\n".join(context_samples))
                    if questions:
                        st.session_state.gold_questions = questions
                        gold_dataset_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(gold_dataset_path, "w", encoding="utf-8") as f:
                            json.dump(questions, f, indent=2)
                        st.success(f"Generated {len(questions)} questions and saved to file.")
                        st.rerun()
                    else:
                        st.error("Empty response from Gemini.")
            else:
                st.error("Text chunks file not found.")
    with col_reset:
        if st.button("Delete Dataset"):
            if gold_dataset_path.exists():
                os.remove(gold_dataset_path)
            st.session_state.gold_questions = []
            st.session_state.eval_results = []
            st.rerun()

    if st.session_state.gold_questions:
        st.divider()
        st.subheader(f"Step 2: Evaluate {selected_exp}")
        with st.expander(f"View Gold Dataset ({len(st.session_state.gold_questions)} Pairs)", expanded=False):
            for idx, question in enumerate(st.session_state.gold_questions, start=1):
                st.markdown(f"**Q{idx}: {question.get('question')}**")
                st.caption(f"Ref Answer: {question.get('answer')}")
                st.markdown("---")

        if st.button("Run Evaluation", type="primary"):
            async def run_full_evaluation_session():
                qa_engine = RAGQueryEngine(selected_exp)
                await qa_engine.initialize()
                evaluator = GeminiEvaluator()
                session_results = []
                total_q = len(st.session_state.gold_questions)
                for idx, q_item in enumerate(st.session_state.gold_questions):
                    my_bar.progress((idx) / total_q, text=f"Processing Q{idx + 1}/{total_q}...")
                    rag_answer = await qa_engine.query(q_item.get("question"))
                    score = evaluator.evaluate_answer(q_item.get("question"), q_item.get("answer"), rag_answer)
                    session_results.append(
                        {
                            "Question": q_item.get("question"),
                            "RAG Answer": rag_answer,
                            "Gold Answer": q_item.get("answer"),
                            "Faithfulness": score.get("faithfulness_score", 0),
                            "Completeness": score.get("completeness_score", 0),
                            "Reasoning": score.get("reasoning", ""),
                        }
                    )
                return session_results

            my_bar = st.progress(0, text="Initializing Engine...")
            st.session_state.eval_results = asyncio.run(run_full_evaluation_session())
            my_bar.progress(1.0, text="Done!")
            st.success("Evaluation finished.")

    if st.session_state.eval_results:
        df = pd.DataFrame(st.session_state.eval_results)
        m1, m2, m3 = st.columns(3)
        m1.metric("Avg Faithfulness", f"{df['Faithfulness'].mean():.1f}/10")
        m2.metric("Avg Completeness", f"{df['Completeness'].mean():.1f}/10")
        m3.info("Score by Gemini 2.5 Flash")
        st.dataframe(df[["Question", "Faithfulness", "Completeness", "Reasoning"]].astype(str), hide_index=False)
        with st.expander("Compare Answers (Detailed View)"):
            for idx, row in df.iterrows():
                st.markdown(f"**Q: {row['Question']}**")
                c1, c2 = st.columns(2)
                with c1:
                    st.info(f"RAG: {row['RAG Answer']}")
                with c2:
                    st.success(f"Gold: {st.session_state.gold_questions[idx]['answer']}")
                st.caption(f"Judge: {row['Reasoning']}")
                st.divider()


def _render_chat_tab(selected_exp: str):
    st.header("Chat with Document")
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask a question..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner(f"Querying {selected_exp}..."):
                qa_engine = RAGQueryEngine(selected_exp)
                response = asyncio.run(qa_engine.query(prompt))
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})


def render_dashboard():
    st.set_page_config(
        page_title="RAG-Anything Workbench",
        page_icon="🧬",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
            .stTabs [data-baseweb="tab-list"] { gap: 10px; }
            .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 4px 4px 0px 0px; gap: 1px; padding-top: 10px; padding-bottom: 10px; }
            .stTabs [aria-selected="true"] { background-color: #ffffff; border-top: 2px solid #ff4b4b; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    output_path = Path(ENV.output_base_dir)
    selected_exp = _render_sidebar(output_path)
    tab1, tab2, tab3, tab4 = st.tabs([
        "Graph & Metrics",
        "Pruning Benchmark",
        "AI Judge (Gemini)",
        "Chat Playground",
    ])

    if not selected_exp:
        st.info("Please select an experiment from the sidebar.")
        return

    with tab1:
        _render_metrics_tab(selected_exp, output_path)
    with tab2:
        _render_pruning_tab(selected_exp, output_path)
    with tab3:
        _render_judge_tab(selected_exp, output_path)
    with tab4:
        _render_chat_tab(selected_exp)
