#!/usr/bin/env python3
"""Build human-consensus ground truth for EmergingArt annotations.

The ground-truth unit is one canonical six-image episode, represented by the
corresponding group in EmergingArt/data/Overall.json. Other benchmark splits are
views of these same episodes, so this script only uses the three selected
annotators' Overall rankings to build the labels.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "EmergingArt" / "data"
ANNOTATION_DIR = SCRIPT_DIR / "HumanAnnotations"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "HumanAnnotations.json"

SELECTED_ANNOTATORS = ("xieyu", "zhexuan_cui", "fengxain_ji")
SPLIT_NAMES = (
    "Overall",
    "Low-price",
    "Mid-price",
    "High-price",
    "Near-Tie-low",
    "Near-Tie-high",
)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sort_folder_ids(folder_ids: list[str]) -> tuple[str, ...]:
    return tuple(sorted(folder_ids, key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value)))


def load_split_groups(split_name: str) -> dict[int, list[dict[str, Any]]]:
    path = DATA_DIR / f"{split_name}.json"
    rows = read_json(path)
    groups: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        group_id = int(row["group_id"])
        item = dict(row)
        item["folder_id"] = str(item["folder_id"])
        item["price"] = float(item["price"])
        groups.setdefault(group_id, []).append(item)

    for group_id, items in groups.items():
        if len(items) != 6:
            raise ValueError(f"{split_name} group {group_id} has {len(items)} items, expected 6")
    return dict(sorted(groups.items()))


def group_key(items: list[dict[str, Any]]) -> tuple[str, ...]:
    return sort_folder_ids([item["folder_id"] for item in items])


def annotation_path(annotator: str) -> Path:
    return ANNOTATION_DIR / f"emergingart_annotations_{annotator}.json"


def load_overall_rankings(annotator: str) -> dict[int, list[str]]:
    path = annotation_path(annotator)
    store = read_json(path)
    ranking_direction = store.get("ranking_direction")
    if ranking_direction != "rank_1_is_most_preferred":
        raise ValueError(f"{path} has unsupported ranking_direction={ranking_direction!r}")

    rankings: dict[int, list[str]] = {}
    for record in store.get("records", {}).values():
        if record.get("dataset") != "Overall":
            continue
        group_id = int(record["group_id"])
        ranking = [str(folder_id) for folder_id in record["ranked_folder_ids"]]
        if len(ranking) != 6 or len(set(ranking)) != 6:
            raise ValueError(f"{path} Overall group {group_id} has an invalid ranking")
        rankings[group_id] = ranking
    return rankings


def validate_rankings(
    overall_groups: dict[int, list[dict[str, Any]]],
    rankings_by_annotator: dict[str, dict[int, list[str]]],
) -> None:
    expected_group_ids = set(overall_groups)
    for annotator, rankings in rankings_by_annotator.items():
        missing = sorted(expected_group_ids - set(rankings))
        extra = sorted(set(rankings) - expected_group_ids)
        if missing or extra:
            raise ValueError(
                f"{annotator} Overall coverage mismatch: missing={missing[:10]}, extra={extra[:10]}"
            )
        for group_id, ranking in rankings.items():
            expected = set(item["folder_id"] for item in overall_groups[group_id])
            if set(ranking) != expected:
                raise ValueError(
                    f"{annotator} Overall group {group_id} ranking ids do not match data ids"
                )


def pairwise_probability(
    folder_ids: list[str],
    annotator_rankings: dict[str, list[str]],
) -> tuple[dict[str, dict[str, float | None]], list[dict[str, Any]], dict[str, int]]:
    positions = {
        annotator: {folder_id: rank for rank, folder_id in enumerate(ranking, start=1)}
        for annotator, ranking in annotator_rankings.items()
    }
    annotator_count = len(annotator_rankings)

    matrix: dict[str, dict[str, float | None]] = {
        folder_id: {other_id: None for other_id in folder_ids} for folder_id in folder_ids
    }
    pairs: list[dict[str, Any]] = []
    unanimous_pairs = 0
    majority_pairs = 0

    for left, right in itertools.combinations(folder_ids, 2):
        left_votes = sum(
            1 for pos in positions.values() if pos[left] < pos[right]
        )
        right_votes = annotator_count - left_votes
        left_probability = left_votes / annotator_count
        right_probability = right_votes / annotator_count
        matrix[left][right] = round(left_probability, 10)
        matrix[right][left] = round(right_probability, 10)

        if left_votes in (0, annotator_count):
            unanimous_pairs += 1
        else:
            majority_pairs += 1

        pairs.append(
            {
                "item_i": left,
                "item_j": right,
                "p_i_preferred_over_j": round(left_probability, 10),
                "votes_i_preferred_over_j": left_votes,
                "votes_j_preferred_over_i": right_votes,
            }
        )

    strength = {
        "unanimous_pairs": unanimous_pairs,
        "majority_pairs": majority_pairs,
        "total_pairs": math.comb(len(folder_ids), 2),
    }
    return matrix, pairs, strength


def kemeny_consensus(
    folder_ids: list[str],
    probability_matrix: dict[str, dict[str, float | None]],
    annotator_rankings: dict[str, list[str]],
) -> dict[str, Any]:
    mean_rank = {
        folder_id: sum(
            ranking.index(folder_id) + 1 for ranking in annotator_rankings.values()
        )
        / len(annotator_rankings)
        for folder_id in folder_ids
    }

    best_score = -1.0
    best_orders: list[tuple[str, ...]] = []
    for permutation in itertools.permutations(folder_ids):
        score = 0.0
        for earlier_index in range(len(permutation)):
            for later_index in range(earlier_index + 1, len(permutation)):
                preferred = permutation[earlier_index]
                other = permutation[later_index]
                value = probability_matrix[preferred][other]
                if value is None:
                    raise ValueError("pairwise probability matrix contains an unexpected diagonal lookup")
                score += value
        if score > best_score + 1e-12:
            best_score = score
            best_orders = [permutation]
        elif abs(score - best_score) <= 1e-12:
            best_orders.append(permutation)

    def tie_break_key(order: tuple[str, ...]) -> tuple[tuple[float, ...], tuple[int | str, ...]]:
        mean_rank_vector = tuple(mean_rank[folder_id] for folder_id in order)
        folder_id_vector: tuple[int | str, ...] = tuple(
            int(folder_id) if folder_id.isdigit() else folder_id for folder_id in order
        )
        return mean_rank_vector, folder_id_vector

    selected = min(best_orders, key=tie_break_key)
    return {
        "ranking": list(selected),
        "score": round(best_score, 6),
        "max_possible_score": math.comb(len(folder_ids), 2),
        "tie_count": len(best_orders),
        "tie_break": "minimum annotator mean-rank vector, then folder_id",
    }


def build_split_mapping(overall_groups: dict[int, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    overall_key_to_group_id = {group_key(items): group_id for group_id, items in overall_groups.items()}
    mapping: dict[str, dict[str, Any]] = {}

    for split_name in SPLIT_NAMES:
        split_groups = load_split_groups(split_name)
        group_to_canonical: dict[str, int] = {}
        for split_group_id, items in split_groups.items():
            key = group_key(items)
            if key not in overall_key_to_group_id:
                raise ValueError(f"{split_name} group {split_group_id} does not map to Overall")
            group_to_canonical[str(split_group_id)] = overall_key_to_group_id[key]

        unique_canonical_ids = sorted(set(group_to_canonical.values()))
        mapping[split_name] = {
            "num_groups": len(split_groups),
            "num_unique_canonical_episodes": len(unique_canonical_ids),
            "group_to_canonical_overall_group_id": group_to_canonical,
        }
    return mapping


def build_ground_truth() -> dict[str, Any]:
    overall_groups = load_split_groups("Overall")
    rankings_by_annotator = {
        annotator: load_overall_rankings(annotator) for annotator in SELECTED_ANNOTATORS
    }
    validate_rankings(overall_groups, rankings_by_annotator)

    episodes: dict[str, Any] = {}
    for group_id, items in overall_groups.items():
        folder_ids = [item["folder_id"] for item in items]
        annotator_rankings = {
            annotator: rankings[group_id]
            for annotator, rankings in rankings_by_annotator.items()
        }
        matrix, pairs, strength = pairwise_probability(folder_ids, annotator_rankings)
        kemeny = kemeny_consensus(folder_ids, matrix, annotator_rankings)

        episodes[str(group_id)] = {
            "canonical_group_id": group_id,
            "item_count": len(items),
            "folder_ids_source_order": folder_ids,
            "items": [
                {
                    "folder_id": item["folder_id"],
                    "price": item["price"],
                    "folder_path": item.get("folder_path", ""),
                }
                for item in items
            ],
            "annotator_rankings": annotator_rankings,
            "pairwise_preference_matrix": matrix,
            "pairwise_preferences": pairs,
            "pairwise_consensus_strength": strength,
            "kemeny_consensus": kemeny,
        }

    return {
        "schema_version": 1,
        "created_at": now_iso(),
        "dataset_name": "EmergingArt",
        "ranking_direction": "rank_1_is_most_preferred",
        "canonical_unit": "one Overall six-image group, identified by the unordered set of six folder_ids",
        "ground_truth_definition": {
            "primary": "annotator-averaged pairwise preference probability p_ij",
            "formula": "p_ij = (1 / 3) * sum_a 1[rank_a(i) < rank_a(j)]",
            "hard_ranking": "Kemeny consensus ranking maximizing sum_{m<n} p_{pi_m,pi_n}",
            "annotator_weighting": "equal weight per annotator",
            "selected_annotators": list(SELECTED_ANNOTATORS),
        },
        "source_files": {
            annotator: str(annotation_path(annotator).relative_to(SCRIPT_DIR))
            for annotator in SELECTED_ANNOTATORS
        },
        "num_canonical_episodes": len(episodes),
        "items_per_episode": 6,
        "pairwise_labels_per_episode": math.comb(6, 2),
        "possible_pairwise_probabilities": [0.0, round(1 / 3, 10), round(2 / 3, 10), 1.0],
        "split_mappings": build_split_mapping(overall_groups),
        "episodes": episodes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build EmergingArt human-consensus pairwise and Kemeny ground truth."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output JSON path. Defaults to {DEFAULT_OUTPUT_PATH}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_ground_truth()
    write_json(args.output, payload)
    print(f"Wrote {payload['num_canonical_episodes']} canonical episodes to {args.output}")


if __name__ == "__main__":
    main()
