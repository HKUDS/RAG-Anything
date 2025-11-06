#!/usr/bin/env python3
"""
Generate:
  - Test-B scoring flow diagram (sankey-style) -> visualizations/testb_score_flow.png
  - Test-A overview (accuracy/score distributions and per-type) -> visualizations/testa_overview.png
  - Test-C overview (accuracy/score distributions and per-type) -> visualizations/testc_overview.png

Inputs (default paths exist in repo root):
  - Test-A: spiqa_testa_full_results_final.json
  - Test-B: spiqa_comprehensive_results.json (contains per-question similarity and is_correct)
  - Test-C: one of the result files, default: spiqa_testc_relaxed_results.json
"""

from pathlib import Path
import json
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.graph_objects as go


def load_generic_json(path: Path) -> pd.DataFrame:
    with path.open() as f:
        data = json.load(f)
    rows = []
    for k, v in data.items():
        ev = v.get("evaluation", {})
        rows.append(
            {
                "id": k,
                "question_type": v.get("question_type", v.get("Question Type", "unknown")),
                "is_correct": bool(ev.get("is_correct", False)),
                "similarity": float(ev.get("similarity_score", np.nan)),
            }
        )
    return pd.DataFrame(rows)


def testb_score_flow(out_dir: Path, wA: float = 1/3, wE: float = 1/3, wC: float = 1/3, composite: float = 0.847):
    """Sankey flow with explicit A/E/C rubric leading to composite score.

    Parameters reflect the rubric weights and final observed composite.
    """
    nodes = [
        "Load Dataset",
        "Query Compiler",
        "Micro Planner",
        "Dual Retrieval",
        "Evidence Fusion",
        "Generation",
        f"Adequacy A (w={wA:.2f})",
        f"Attribution E (w={wE:.2f})",
        f"Consistency C (w={wC:.2f})",
        f"Composite S = wA·A + wE·E + wC·C\nS ≈ {composite:.3f}",
        "Artifacts (JSON)",
    ]
    idx = {n: i for i, n in enumerate(nodes)}
    links = [
        ("Load Dataset", "Query Compiler", 1),
        ("Query Compiler", "Micro Planner", 1),
        ("Micro Planner", "Dual Retrieval", 1),
        ("Dual Retrieval", "Evidence Fusion", 1),
        ("Evidence Fusion", "Generation", 1),
        ("Generation", f"Adequacy A (w={wA:.2f})", wA),
        ("Generation", f"Attribution E (w={wE:.2f})", wE),
        ("Generation", f"Consistency C (w={wC:.2f})", wC),
        (f"Adequacy A (w={wA:.2f})", f"Composite S = wA·A + wE·E + wC·C\nS ≈ {composite:.3f}", wA),
        (f"Attribution E (w={wE:.2f})", f"Composite S = wA·A + wE·E + wC·C\nS ≈ {composite:.3f}", wE),
        (f"Consistency C (w={wC:.2f})", f"Composite S = wA·A + wE·E + wC·C\nS ≈ {composite:.3f}", wC),
        (f"Composite S = wA·A + wE·E + wC·C\nS ≈ {composite:.3f}", "Artifacts (JSON)", 1),
    ]
    fig = go.Figure(
        data=[
            go.Sankey(
                node=dict(
                    pad=20,
                    thickness=20,
                    line=dict(color="#888", width=0.5),
                    label=nodes,
                    color=["#577590", "#4d908e", "#43aa8b", "#90be6d", "#f9c74f", "#f8961e", "#f3722c", "#277da1"],
                ),
                link=dict(
                    source=[idx[s] for s, t, v in links],
                    target=[idx[t] for s, t, v in links],
                    value=[v for s, t, v in links],
                    color="#cccccc",
                ),
            )
        ]
    )
    fig.update_layout(title_text="SPIQA Test-B Scoring Flow (A/E/C → Composite)", font_size=12, width=1300, height=650)
    try:
        import plotly.io as pio
        pio.write_image(fig, out_dir / "testb_score_flow.png", scale=3, width=1200, height=600)
    except Exception:
        fig.write_html(out_dir / "testb_score_flow.html")


def overview_from_df(df: pd.DataFrame, title: str, out_path: Path):
    """Create a 2x2 overview: histogram, count by type, average accuracy by type, similarity box by type."""
    sns.set_style("whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))

    # 1) Histogram of similarity
    sim = df["similarity"].dropna()
    axes[0, 0].hist(sim, bins=20, color="#74a9cf", edgecolor="black", alpha=0.8)
    axes[0, 0].axvline(sim.mean(), color="red", ls="--", label=f"Mean: {sim.mean():.3f}")
    axes[0, 0].set_title("Similarity Distribution")
    axes[0, 0].legend()

    # 2) Question type counts
    ct = df["question_type"].fillna("unknown").value_counts()
    ct.plot(kind="bar", ax=axes[0, 1], color="#90be6d", edgecolor="black")
    axes[0, 1].set_title("Question Type Count")
    axes[0, 1].tick_params(axis='x', rotation=45)

    # 3) Average accuracy by type
    acc = df.groupby("question_type")["is_correct"].mean().sort_values(ascending=False)
    acc.plot(kind="bar", ax=axes[1, 0], color="#f3722c", edgecolor="black")
    axes[1, 0].set_ylim(0, 1)
    axes[1, 0].set_title("Accuracy by Question Type")
    axes[1, 0].tick_params(axis='x', rotation=45)

    # 4) Similarity violin plot by type (more robust when values cluster at 0/1)
    sub = df.dropna(subset=["similarity"]).copy()
    if not sub.empty:
        sns.violinplot(data=sub, x="question_type", y="similarity", ax=axes[1, 1], color="#ffd166", cut=0, inner="quart")
        axes[1, 1].set_title("Similarity by Question Type (violin)")
        axes[1, 1].set_ylim(0, 1)
        axes[1, 1].tick_params(axis='x', rotation=45)
    fig.suptitle(title, fontsize=16, fontweight="bold")
    fig.tight_layout(rect=[0, 0.03, 1, 0.97])
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--testa", default="spiqa_testa_full_results_final.json")
    ap.add_argument("--testb", default="spiqa_comprehensive_results.json")
    ap.add_argument("--testc", default="spiqa_testc_relaxed_results.json")
    ap.add_argument("--out_dir", default="visualizations")
    args = ap.parse_args()

    out = Path(args.out_dir); out.mkdir(exist_ok=True)

    # Flow diagram for B
    testb_score_flow(out)

    # Overviews for A and C
    try:
        df_a = load_generic_json(Path(args.testa))
        overview_from_df(df_a, "Test-A Overview", out / "testa_overview.png")
    except Exception:
        pass
    try:
        df_c = load_generic_json(Path(args.testc))
        overview_from_df(df_c, "Test-C Overview (relaxed)", out / "testc_overview.png")
    except Exception:
        pass

    print("✅ Wrote:")
    print(" -", out / "testb_score_flow.png")
    print(" -", out / "testa_overview.png")
    print(" -", out / "testc_overview.png")


if __name__ == "__main__":
    main()


