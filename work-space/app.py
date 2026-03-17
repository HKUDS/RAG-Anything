import sys
import os
import asyncio
import json
import pandas as pd
import streamlit as st
from pathlib import Path

# ==========================================
# 1. SYSTEM PATH FIX
# ==========================================
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# ==========================================
# 2. IMPORTS
# ==========================================
from src.config import ENV
from src.visualizer import GraphVisualizer
from src.qa_engine import RAGQueryEngine
from src.pruning_algorithms import PRUNING_ALGORITHMS, list_algorithms
from src.pruning_evaluator import PruningBenchmark, PruningEvaluator

try:
    from src.evaluator import GeminiEvaluator
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

# ==========================================
# 3. STREAMLIT SETUP
# ==========================================
st.set_page_config(
    page_title="RAG-Anything Workbench",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 4px 4px 0px 0px; gap: 1px; padding-top: 10px; padding-bottom: 10px; }
    .stTabs [aria-selected="true"] { background-color: #ffffff; border-top: 2px solid #ff4b4b; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 4. SIDEBAR & CONFIG
# ==========================================
st.sidebar.title("🎛️ Experiment Control")

output_path = Path(ENV.output_base_dir)
if output_path.exists():
    exp_dirs = sorted([d.name for d in output_path.iterdir() if d.is_dir()])
else:
    exp_dirs = []

if not exp_dirs:
    st.sidebar.warning("No experiments found. Run 'run_bench.py' first.")
    selected_exp = None
else:
    selected_exp = st.sidebar.selectbox(
        "Select Experiment", 
        exp_dirs, 
        index=len(exp_dirs)-1
    )
    st.sidebar.success(f"Loaded: {selected_exp}")

st.sidebar.divider()
st.sidebar.info(f"**Server:** {ENV.ollama_base_url}")
st.sidebar.info(f"**Default LLM:** {ENV.ollama_llm}")

# ==========================================
# 5. MAIN TABS
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Graph & Metrics",
    "🔬 Pruning Benchmark",
    "⚖️ AI Judge (Gemini)",
    "💬 Chat Playground"
])

if selected_exp:
    # --- TAB 1: VISUALIZATION ---
    with tab1:
        st.header(f"Experiment Analysis: {selected_exp}")
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.subheader("📈 Benchmark Metrics")
            if Path(ENV.report_file).exists():
                try:
                    df = pd.read_csv(ENV.report_file)
                    exp_data = df[df['Experiment_ID'] == selected_exp]
                    
                    if not exp_data.empty:
                        display_df = exp_data.T
                        display_df.columns = ["Value"]
                        
                        # --- FIX LỖI PYARROW Ở ĐÂY ---
                        # Ép kiểu sang string để tránh lỗi mixed types (float/int/str)
                        display_df = display_df.astype(str) 
                        # -----------------------------
                        
                        st.dataframe(display_df, hide_index=False)
                    else:
                        st.warning("Metrics not recorded yet.")
                except Exception as e:
                    st.error(f"Error reading CSV: {e}")
            else:
                st.warning("No benchmark_report.csv found.")
        
        with col2:
            st.subheader("🕸️ Knowledge Graph Topology")

            # Pruning Algorithm Selector
            algorithm_options = {alg["id"]: f"{alg['name']}" for alg in list_algorithms()}
            selected_algorithm = st.selectbox(
                "Pruning Algorithm",
                options=list(algorithm_options.keys()),
                format_func=lambda x: algorithm_options[x],
                index=list(algorithm_options.keys()).index("hybrid"),  # Default to hybrid
                help="Choose which algorithm to use for selecting the most important nodes to display"
            )

            max_nodes = st.slider("Max nodes to display", min_value=20, max_value=300, value=ENV.pruning_max_nodes, step=10)

            if st.button("Generate Interactive Graph", type="primary"):
                storage_dir = output_path / selected_exp / "rag_storage"
                with st.spinner(f"Visualizing with {algorithm_options[selected_algorithm]}..."):
                    viz = GraphVisualizer(str(storage_dir))
                    html_path = viz.generate_html(max_nodes=max_nodes, algorithm_id=selected_algorithm)

                    if html_path:
                        with open(html_path, 'r', encoding='utf-8') as f:
                            html_content = f.read()
                        st.components.v1.html(html_content, height=600, scrolling=True)
                        st.caption(f"Top-{max_nodes} nodes using **{algorithm_options[selected_algorithm]}** algorithm.")
                    else:
                        st.error("Graph file not found.")

    # --- TAB 2: PRUNING BENCHMARK ---
    with tab2:
        st.header("🔬 Pruning Algorithm Benchmark")
        st.markdown("""
        Compare different pruning algorithms to find which one selects the most **important** and **representative** nodes.

        **Metrics:**
        - **Hub Retention**: % of top-degree nodes (key concepts) retained
        - **Bridge Retention**: % of bridge nodes (connecting clusters) retained
        - **Cluster Coverage**: % of communities with at least 1 representative
        - **Connectivity**: How connected is the pruned graph
        - **LLM Score**: AI evaluation of node selection quality (optional)
        """)

        st.divider()

        # Settings
        col_settings1, col_settings2 = st.columns(2)
        with col_settings1:
            benchmark_max_nodes = st.number_input(
                "Max Nodes for Benchmark",
                min_value=10,
                max_value=200,
                value=ENV.pruning_max_nodes,
                help="Number of nodes to prune to for evaluation"
            )
        with col_settings2:
            enable_llm_eval = st.checkbox(
                "Enable LLM Evaluation",
                value=False,
                help="Use LLM to evaluate pruning quality (slower, may have API limits)"
            )

        # Run Benchmark
        if st.button("🚀 Run Benchmark", type="primary", key="run_pruning_benchmark"):
            storage_dir = output_path / selected_exp / "rag_storage"
            viz = GraphVisualizer(str(storage_dir))
            G_full = viz.get_full_graph()

            if G_full is None:
                st.error("Could not load graph. Make sure the experiment has been run.")
            else:
                st.info(f"Full graph: **{G_full.number_of_nodes()}** nodes, **{G_full.number_of_edges()}** edges")

                with st.spinner("Running benchmark on all algorithms..."):
                    try:
                        benchmark = PruningBenchmark(G_full, max_nodes=benchmark_max_nodes)

                        if enable_llm_eval and HAS_GEMINI and ENV.google_api_key:
                            # Run with LLM evaluation
                            from src.models import get_model_funcs
                            llm_func, _, _ = get_model_funcs("ollama")

                            async def run_with_llm():
                                return await benchmark.run_with_llm(PRUNING_ALGORITHMS, llm_func)

                            results = asyncio.run(run_with_llm())
                        else:
                            # Run without LLM
                            results = benchmark.run(PRUNING_ALGORITHMS)

                        # Store results in session state
                        st.session_state.pruning_results = results
                        st.session_state.pruning_summary = benchmark.get_summary()

                        # Export to CSV
                        csv_path = Path(ENV.pruning_benchmark_report)
                        benchmark.to_csv(str(csv_path))
                        st.success(f"Benchmark complete! Results saved to `{csv_path}`")

                    except Exception as e:
                        st.error(f"Benchmark failed: {e}")
                        import traceback
                        traceback.print_exc()

        # Display Results
        if "pruning_results" in st.session_state and st.session_state.pruning_results:
            st.divider()
            st.subheader("📊 Benchmark Results")

            results = st.session_state.pruning_results

            # Best Algorithm Highlight
            best = results[0]
            st.success(f"**Recommended:** {best.algorithm_name} (Score: {best.weighted_score:.4f})")

            # Results Table
            results_data = []
            for r in results:
                row = {
                    "Algorithm": r.algorithm_name,
                    "Nodes": r.actual_nodes,
                    "Edges": r.actual_edges,
                    "Hub Ret.": f"{r.hub_retention:.2%}",
                    "Bridge Ret.": f"{r.bridge_retention:.2%}",
                    "Cluster Cov.": f"{r.cluster_coverage:.2%}",
                    "Connectivity": f"{r.connectivity:.2%}",
                    "LLM Score": f"{r.llm_score:.2f}" if r.llm_score is not None else "N/A",
                    "Total Score": f"{r.weighted_score:.4f}",
                }
                results_data.append(row)

            df_results = pd.DataFrame(results_data)
            st.dataframe(df_results, hide_index=True, use_container_width=True)

            # Bar Chart Comparison
            st.subheader("📈 Score Comparison")
            chart_data = pd.DataFrame({
                "Algorithm": [r.algorithm_name for r in results],
                "Hub Retention": [r.hub_retention for r in results],
                "Bridge Retention": [r.bridge_retention for r in results],
                "Cluster Coverage": [r.cluster_coverage for r in results],
                "Connectivity": [r.connectivity for r in results],
            })
            chart_data = chart_data.set_index("Algorithm")
            st.bar_chart(chart_data)

            # Summary Text
            with st.expander("📝 Full Summary"):
                st.code(st.session_state.pruning_summary)

# --- TAB 3: AI EVALUATION ---
    with tab3:
        st.header("🤖 Automated Evaluation with Gemini")
        
        # Đường dẫn file lưu dataset
        GOLD_DATASET_PATH = Path("gold_dataset.json")
        
        if not HAS_GEMINI:
            st.error("Google Generative AI library not installed.")
        elif not ENV.google_api_key:
            st.error("Missing GOOGLE_API_KEY in .env file.")
        else:
            # 1. Load Dataset từ file (nếu có) khi khởi động
            if "gold_questions" not in st.session_state:
                if GOLD_DATASET_PATH.exists():
                    try:
                        with open(GOLD_DATASET_PATH, 'r', encoding='utf-8') as f:
                            st.session_state.gold_questions = json.load(f)
                        # st.toast("Dataset loaded from file!", icon="📂") 
                    except Exception as e:
                        st.error(f"Error loading dataset: {e}")
                        st.session_state.gold_questions = []
                else:
                    st.session_state.gold_questions = []

            if "eval_results" not in st.session_state:
                st.session_state.eval_results = []

            # 2. Control Panel
            st.subheader("Step 1: Test Dataset Management")
            
            col_gen, col_reset = st.columns([1, 4])
            
            with col_gen:
                # Nút sinh câu hỏi mới (Nếu chưa có hoặc muốn làm mới)
                btn_label = "Generate New Questions" if not st.session_state.gold_questions else "Regenerate Questions"
                if st.button(btn_label, type="primary" if not st.session_state.gold_questions else "secondary"):
                    chunk_file = output_path / selected_exp / "rag_storage" / "kv_store_text_chunks.json"
                    
                    if chunk_file.exists():
                        with st.spinner("Gemini is reading document to generate QA pairs..."):
                            try:
                                with open(chunk_file, 'r', encoding='utf-8') as f:
                                    chunks = json.load(f)
                                # Lấy mẫu text từ 15 chunk đầu tiên
                                context_samples = [c['content'] for c in list(chunks.values())[:15]]
                                context_text = "\n".join(context_samples)
                                
                                evaluator = GeminiEvaluator()
                                questions = evaluator.generate_gold_questions(context_text)
                                
                                if questions:
                                    st.session_state.gold_questions = questions
                                    # LƯU FILE NGAY LẬP TỨC
                                    with open(GOLD_DATASET_PATH, 'w', encoding='utf-8') as f:
                                        json.dump(questions, f, indent=2)
                                    st.success(f"Generated {len(questions)} questions & Saved to file!")
                                    st.rerun() # Refresh để hiện UI mới
                                else:
                                    st.error("Empty response from Gemini.")
                            except Exception as e:
                                st.error(f"Error generating questions: {e}")
                    else:
                        st.error("Text chunks file not found. Have you run the benchmark?")

            with col_reset:
                # Nút xóa dataset để làm lại từ đầu
                if st.button("Delete Dataset"):
                    if GOLD_DATASET_PATH.exists():
                        os.remove(GOLD_DATASET_PATH)
                    st.session_state.gold_questions = []
                    st.session_state.eval_results = []
                    st.rerun()

            # 3. Hiển thị & Chấm điểm
            if st.session_state.gold_questions:
                st.divider()
                st.subheader(f"Step 2: Evaluate '{selected_exp}'")
                
                with st.expander(f"View Gold Dataset ({len(st.session_state.gold_questions)} Pairs)", expanded=False):
                    for i, q in enumerate(st.session_state.gold_questions):
                        st.markdown(f"**Q{i+1}: {q.get('question')}**")
                        st.caption(f"Ref Answer: {q.get('answer')}")
                        st.markdown("---")

                if st.button("🚀 Run Evaluation", type="primary"):
                    # --- FIX ASYNCIO LOOP ISSUE ---
                    # Định nghĩa một hàm async to để chạy trọn gói quy trình
                    async def run_full_evaluation_session():
                        # 1. Khởi tạo Engine BÊN TRONG hàm async
                        # Để đảm bảo nó gắn với Event Loop hiện tại
                        qa_engine_local = RAGQueryEngine(selected_exp)
                        await qa_engine_local.initialize()
                        
                        local_evaluator = GeminiEvaluator()
                        session_results = []
                        
                        total_q = len(st.session_state.gold_questions)
                        
                        # 2. Chạy vòng lặp BÊN TRONG hàm async
                        for idx, q_item in enumerate(st.session_state.gold_questions):
                            q_text = q_item.get('question')
                            gold_ans = q_item.get('answer')
                            
                            # Cập nhật UI (Streamlit hỗ trợ update từ async)
                            my_bar.progress((idx) / total_q, text=f"Processing Q{idx+1}/{total_q}...")
                            
                            # A. RAG Query (Không dùng asyncio.run ở đây nữa, dùng await)
                            rag_ans = await qa_engine_local.query(q_text)
                            
                            # B. Judge (Sync func)
                            score = local_evaluator.evaluate_answer(q_text, gold_ans, rag_ans)
                            
                            session_results.append({
                                "Question": q_text,
                                "RAG Answer": rag_ans,
                                "Gold Answer": gold_ans,
                                "Faithfulness": score.get('faithfulness_score', 0),
                                "Completeness": score.get('completeness_score', 0),
                                "Reasoning": score.get('reasoning', '')
                            })
                        
                        return session_results

                    # --- MAIN EXECUTION ---
                    try:
                        my_bar = st.progress(0, text="Initializing Engine...")
                        
                        # Chỉ gọi asyncio.run ĐÚNG MỘT LẦN ở ngoài cùng
                        results = asyncio.run(run_full_evaluation_session())
                        
                        my_bar.progress(1.0, text="Done!")
                        st.session_state.eval_results = results
                        st.success("Evaluation Finished!")
                        
                    except Exception as e:
                        st.error(f"Critical Error during evaluation: {e}")
                        # In chi tiết lỗi ra console để debug nếu cần
                        import traceback
                        traceback.print_exc()

            # 4. Hiển thị Kết quả
            if st.session_state.eval_results:
                res_df = pd.DataFrame(st.session_state.eval_results)
                
                # Metrics Dashboard
                m1, m2, m3 = st.columns(3)
                avg_faith = res_df['Faithfulness'].mean()
                avg_comp = res_df['Completeness'].mean()
                
                m1.metric("Avg Faithfulness", f"{avg_faith:.1f}/10", 
                          delta="High" if avg_faith > 8 else "Low", 
                          delta_color="normal")
                m2.metric("Avg Completeness", f"{avg_comp:.1f}/10",
                          delta="High" if avg_comp > 8 else "Low",
                          delta_color="normal")
                m3.info("Score by Gemini 2.5 Flash")
                
                # Detailed Table
                st.dataframe(
                    res_df[['Question', 'Faithfulness', 'Completeness', 'Reasoning']].astype(str), 
                    hide_index=False
                )
                
                # Expander xem chi tiết câu trả lời
                with st.expander("Compare Answers (Detailed View)"):
                    for idx, row in res_df.iterrows():
                        st.markdown(f"**Q: {row['Question']}**")
                        c1, c2 = st.columns(2)
                        with c1:
                            st.info(f"RAG: {row['RAG Answer']}")
                        with c2:
                            st.success(f"Gold: {st.session_state.gold_questions[idx]['answer']}")
                        st.caption(f"Judge: {row['Reasoning']}")
                        st.divider()

    # --- TAB 4: PLAYGROUND ---
    with tab4:
        st.header("💬 Chat with Document")
        
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
                    try:
                        qa_engine = RAGQueryEngine(selected_exp)
                        response = asyncio.run(qa_engine.query(prompt))
                        st.markdown(response)
                        st.session_state.messages.append({"role": "assistant", "content": response})
                    except Exception as e:
                        st.error(f"Error: {e}")

else:
    st.info("👈 Please select an experiment from the sidebar.")
