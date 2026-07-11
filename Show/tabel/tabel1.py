#!/usr/bin/env python3
"""Generate the EmergingArt signal-diagnosis main table.

The script consumes a local snapshot under ``results/`` and aligns every method
to the canonical human episodes by the unordered set of six folder IDs.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
HUMAN_PATH = HERE.parents[1] / "Bechmark" / "HumanAnnotations.json"
EPS = 1e-12

METRIC_NAMES = (
    "BA", "B-R1", "B-R2", "B-R5", "B-R6", "B-tau",
    "VA", "H-R1", "H-R2", "H-R5", "H-R6", "H-tau",
    "B/V-Gap", "V-Gap",
)

STATIC_METHODS = (
    ("CLIPScore", "clipscore_results/CLIPScore.json"),
    ("NIMA", "nima_results/NIMA.json"),
    ("HPSv2", "hpsv2_results/HPSv2.json"),
    ("PickScore", "pickscore_results/PickScore.json"),
    ("ImageReward", "imagereward_results/ImageReward.json"),
    ("RichHF", "richhf_results/RichHF.json"),
    ("Q-Align", "q_align_results/Q-Align.json"),
    ("LLaVA-Reward", "llava_reward_results/LLaVA-Reward.json"),
)

AGENT_METHODS = (
    ("Single-agent (Pair)", "Single-agent_pair/Single-agent_pair.json", True),
    ("Single-agent", "Single-agent_price/Single-agent_price.json", False),
    ("Single-agent (LLM Score)", "Single-agentLLM_score/Single-agentLLM_score.json", False),
    ("Budgeted Single-agent", "Single-agent-Budgeted/Single-agent-Budgeted.json", False),
    ("Valuator Judge", "Valuator_judge/Valuator_judge.json", False),
    ("Valuator", "Auction-arena/Auction-arena.json", False),
)

MODEL_GROUPS = (
    ("Qwen3-VL-4B", "Qwen3-VL-4B", re.compile(r"qwen3-vl-4b", re.I)),
    # These groups remain in the paper template even when valid EmergingArt
    # episode-level files are not available locally.
    ("LLaMA-3.2-11B-Vision", "LLaMA-3.2-11B-Vision", re.compile(r"llama.*11b", re.I)),
    ("Qwen3-VL-30B", "Qwen3-VL-30B", re.compile(r"qwen3-vl-30b", re.I)),
)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def folder_id(item: dict[str, Any]) -> str:
    raw = item.get("folder_id", item.get("name", ""))
    match = re.search(r"\d+", str(raw))
    if not match:
        raise ValueError(f"Cannot extract folder ID from {raw!r}")
    return str(int(match.group()))


def episode_key(items: list[dict[str, Any]]) -> frozenset[str]:
    return frozenset(folder_id(item) for item in items)


def load_human_reference(path: Path) -> dict[frozenset[str], dict[str, Any]]:
    data = read_json(path)
    episodes = data.get("episodes", {})
    iterable = episodes.values() if isinstance(episodes, dict) else episodes
    reference: dict[frozenset[str], dict[str, Any]] = {}
    for episode in iterable:
        ids = [str(value) for value in episode["folder_ids_source_order"]]
        matrix = episode["pairwise_preference_matrix"]
        # Soft Borda score: expected pairwise win rate against the other items.
        human_scores = {
            item_id: sum(float(matrix[item_id][other]) for other in ids if other != item_id)
            / (len(ids) - 1)
            for item_id in ids
        }
        prices = {str(item["folder_id"]): float(item["price"]) for item in episode["items"]}
        reference[frozenset(ids)] = {
            "ids": ids,
            "prices": prices,
            "human_scores": human_scores,
        }
    if len(reference) != 266:
        raise ValueError(f"Expected 266 human episodes, found {len(reference)} in {path}")
    return reference


def baseline_overall(data: dict[str, Any]) -> list[dict[str, Any]]:
    overall = data.get("Overall", {})
    if isinstance(overall, dict):
        return list(overall.get("episodes", []))
    return list(overall)


def method_overall(data: dict[str, Any]) -> list[dict[str, Any]]:
    return list(data.get("datasets", {}).get("Overall", []))


def load_method_episodes(
    path: Path,
    reference: dict[frozenset[str], dict[str, Any]],
    invert_score: bool,
    identity: re.Pattern[str] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    if not path.exists():
        return [], f"missing file: {path.relative_to(HERE)}"
    data = read_json(path)
    if identity is not None:
        model_name = str(data.get("model_name", ""))
        if not identity.search(model_name):
            return [], f"model identity mismatch ({model_name or 'unset'}): {path.relative_to(HERE)}"

    raw_episodes = baseline_overall(data) if "Overall" in data else method_overall(data)
    aligned: list[dict[str, Any]] = []
    seen: set[frozenset[str]] = set()
    for episode in raw_episodes:
        items = episode.get("items", [])
        if len(items) != 6:
            continue
        key = episode_key(items)
        if key not in reference or key in seen:
            continue
        scores: dict[str, float] = {}
        for item in items:
            value = float(item["pred_score"])
            scores[folder_id(item)] = -value if invert_score else value
        if len(scores) != 6 or not all(math.isfinite(value) for value in scores.values()):
            continue
        aligned.append({"reference": reference[key], "scores": scores})
        seen.add(key)
    if not aligned:
        return [], f"no valid aligned episodes: {path.relative_to(HERE)}"
    return aligned, None


def minmax(values: list[float]) -> list[float]:
    low, high = min(values), max(values)
    if high - low <= EPS:
        return [0.0] * len(values)
    return [(value - low) / (high - low) for value in values]


def kendall_tau_b(left: list[float], right: list[float]) -> float:
    concordant = discordant = ties_left = ties_right = 0
    for i in range(len(left)):
        for j in range(i + 1, len(left)):
            dx, dy = left[i] - left[j], right[i] - right[j]
            if abs(dx) <= EPS and abs(dy) <= EPS:
                continue
            if abs(dx) <= EPS:
                ties_left += 1
            elif abs(dy) <= EPS:
                ties_right += 1
            elif dx * dy > 0:
                concordant += 1
            else:
                discordant += 1
    numerator = concordant - discordant
    denominator = math.sqrt(
        (concordant + discordant + ties_left) *
        (concordant + discordant + ties_right)
    )
    return numerator / denominator if denominator > EPS else 0.0


def position_probabilities(values: list[float], position: int) -> list[float]:
    """Per-item probability of occupying a position under random tie-breaking."""
    probabilities = []
    for target_value in values:
        better = sum(value > target_value + EPS for value in values)
        tied = sum(abs(value - target_value) <= EPS for value in values)
        probability = 1.0 / tied if better <= position < better + tied else 0.0
        probabilities.append(probability)
    return probabilities


def rank_position_agreement(
    left: list[float], right: list[float], position: int
) -> float:
    """Expected same-item accuracy when ties on both sides are broken randomly."""
    left_probs = position_probabilities(left, position)
    right_probs = position_probabilities(right, position)
    return sum(a * b for a, b in zip(left_probs, right_probs))


def compute_episode_metrics(episode: dict[str, Any]) -> dict[str, float]:
    ref = episode["reference"]
    ids = ref["ids"]
    z_raw = [episode["scores"][item_id] for item_id in ids]
    z = minmax(z_raw)
    p = [ref["prices"][item_id] for item_id in ids]
    h = [ref["human_scores"][item_id] for item_id in ids]

    b_tau = kendall_tau_b(z, p)
    h_tau = kendall_tau_b(z, h)
    ba = (b_tau + 1.0) / 2.0
    va = (h_tau + 1.0) / 2.0

    z_norm, h_norm = minmax(z), minmax(h)
    gap_errors = [
        abs(abs(z_norm[i] - z_norm[j]) - abs(h_norm[i] - h_norm[j]))
        for i in range(6) for j in range(i + 1, 6)
    ]
    return {
        "BA": ba,
        "B-R1": rank_position_agreement(z, p, 0),
        "B-R2": rank_position_agreement(z, p, 1),
        "B-R5": rank_position_agreement(z, p, 4),
        "B-R6": rank_position_agreement(z, p, 5),
        "B-tau": b_tau,
        "VA": va,
        "H-R1": rank_position_agreement(z, h, 0),
        "H-R2": rank_position_agreement(z, h, 1),
        "H-R5": rank_position_agreement(z, h, 4),
        "H-R6": rank_position_agreement(z, h, 5),
        "H-tau": h_tau,
        "B/V-Gap": abs(ba - va),
        "V-Gap": sum(gap_errors) / len(gap_errors),
    }


def aggregate(episodes: list[dict[str, Any]]) -> dict[str, float]:
    rows = [compute_episode_metrics(episode) for episode in episodes]
    return {name: sum(row[name] for row in rows) / len(rows) for name in METRIC_NAMES}


def fmt(name: str, value: float | None) -> str:
    if value is None:
        return "--"
    if name in {"B-tau", "H-tau", "V-Gap"}:
        return f"{value:.3f}"
    return f"{100.0 * value:.1f}"


def latex_escape(text: str) -> str:
    return text.replace("&", r"\&").replace("_", r"\_")


def latex_row(label: str, metrics: dict[str, float] | None) -> str:
    values = [fmt(name, None if metrics is None else metrics[name]) for name in METRIC_NAMES]
    return f"{label:<25} & " + " & ".join(values) + r" \\"


def render_table(groups: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\setlength{\tabcolsep}{1.0pt}",
        r"\renewcommand{\arraystretch}{0.60}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{lcccccccccccccc}",
        r"\toprule",
        r"\multirow{2}{*}{\textbf{Method}}",
        r"& \multicolumn{6}{c}{\textbf{Behavioral Consistency}}",
        r"& \multicolumn{6}{c}{\textbf{Visual Consistency}}",
        r"& \multicolumn{1}{c}{\textbf{Signal Bias}}",
        r"& \multicolumn{1}{c}{\textbf{Preference Margin}} \\ ",
        r"\cmidrule(lr){2-7}\cmidrule(lr){8-13}\cmidrule(lr){14-14}\cmidrule(lr){15-15}",
        r"& BA$\uparrow$ & B-R1$\uparrow$ & B-R2$\uparrow$ & B-R5$\uparrow$ & B-R6$\uparrow$ & B-$\tau$$\uparrow$",
        r"& VA$\uparrow$ & H-R1$\uparrow$ & H-R2$\uparrow$ & H-R5$\uparrow$ & H-R6$\uparrow$ & H-$\tau$$\uparrow$",
        r"& B/V-Gap$\downarrow$ & V-Gap$\downarrow$ \\ ",
        r"\midrule",
    ]
    for group_index, group in enumerate(groups):
        if group_index:
            lines.append(r"\midrule")
        lines.append(rf"\multicolumn{{15}}{{c}}{{\textit{{{group['label']}}}}} \\ ")
        lines.extend(latex_row(row["label"], row["metrics"]) for row in group["rows"])
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}%",
        r"}",
        r"\caption{Main signal-level diagnosis on EmergingArt Overall. Each method induces an episode-level signal $z$. Behavioral Consistency compares $z$ with transaction-derived prices $p$, while Visual Consistency compares $z$ with the three-annotator soft human preference signal $h$. BA and VA are computed episode-wise as $(\tau_b+1)/2$. Rank-position accuracy reports expected exact-position agreement under independent random tie-breaking on both signals. BA, rank-position accuracy, VA, and B/V-Gap are percentages; Kendall's $\tau_b$ and V-Gap are reported on their native scales. Signal Bias is the episode-level absolute BA--VA difference, and Preference Margin measures pairwise gap distortion relative to human soft-Borda preference strength.}",
        r"\label{tab:emergingart_signal_diagnosis}",
        r"\end{table*}",
    ])
    return "\n".join(lines) + "\n"


def build() -> tuple[list[dict[str, Any]], list[str]]:
    reference = load_human_reference(HUMAN_PATH)
    warnings: list[str] = []
    groups: list[dict[str, Any]] = []

    static_rows = []
    for label, relative in STATIC_METHODS:
        episodes, warning = load_method_episodes(
            RESULTS_DIR / "static" / relative, reference, invert_score=False
        )
        if warning:
            warnings.append(f"{label}: {warning}")
        static_rows.append({"label": label, "n": len(episodes), "metrics": aggregate(episodes) if episodes else None})
    groups.append({"label": "Static visual preference models", "rows": static_rows})

    for label, dirname, identity in MODEL_GROUPS:
        rows = []
        for method_label, relative, invert_score in AGENT_METHODS:
            episodes, warning = load_method_episodes(
                RESULTS_DIR / dirname / relative, reference, invert_score, identity
            )
            if warning:
                warnings.append(f"{label} / {method_label}: {warning}")
            rows.append({
                "label": method_label,
                "n": len(episodes),
                "metrics": aggregate(episodes) if episodes else None,
            })
        groups.append({"label": label, "rows": rows})
    return groups, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "tabel1.tex")
    parser.add_argument("--metrics-output", type=Path, default=HERE / "tabel1_metrics.json")
    args = parser.parse_args()

    groups, warnings = build()
    args.output.write_text(render_table(groups), encoding="utf-8")
    payload = {"metrics": groups, "warnings": warnings}
    args.metrics_output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Wrote {args.metrics_output}")
    for group in groups:
        counts = ", ".join(f"{row['label']}={row['n']}" for row in group["rows"])
        print(f"{group['label']}: {counts}")


if __name__ == "__main__":
    main()
