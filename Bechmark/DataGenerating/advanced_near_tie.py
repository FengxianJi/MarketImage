#!/usr/bin/env python3
"""
高级Near-Tie数据集生成工具

支持：
1. 数据重复使用 - 同一组可以出现在多个数据集中
2. 非连续选择 - 可以跳跃选择，不限于连续区间
3. 多种灵活策略 - 随机、条件筛选、自定义索引等
4. 组合条件 - 支持多个条件的AND/OR组合
"""

import json
import random
from pathlib import Path
from typing import List, Dict, Optional, Union, Callable


class AdvancedNearTieGenerator:
    """高级Near-Tie数据集生成器"""

    def __init__(self, base_path="/mnt/data/user/fengxian.ji/AUCTION/benchmark/EmergingArt"):
        self.base_path = Path(base_path)
        self.data_dir = self.base_path / "data"

    def load_and_merge_sources(self, source_files: List[str]) -> List[Dict]:
        """加载并合并多个源数据文件"""
        print(f"\n加载数据源...")
        all_data = []
        seen_items = set()

        for source_file in source_files:
            source_path = self.data_dir / source_file
            if source_path.exists():
                with open(source_path, 'r') as f:
                    data = json.load(f)
                print(f"  ✓ {source_file}: {len(data)} 项")

                for item in data:
                    folder_id = item['folder_id']
                    if folder_id not in seen_items:
                        all_data.append(item)
                        seen_items.add(folder_id)
            else:
                print(f"  ✗ {source_file}: 文件不存在")

        print(f"合并后总计: {len(all_data)} 项")
        return all_data

    def calculate_group_metrics(self, data: List[Dict]) -> List[Dict]:
        """计算每个组的价格差距指标"""
        print(f"\n计算组指标...")

        groups = {}
        for item in data:
            group_id = item['group_id']
            if group_id not in groups:
                groups[group_id] = []
            groups[group_id].append(item)

        print(f"  共 {len(groups)} 个组")

        group_metrics = []
        for group_id, items in groups.items():
            prices = [item['price'] for item in items]
            if len(prices) >= 2:
                max_price = max(prices)
                min_price = min(prices)
                mean_price = sum(prices) / len(prices)
                price_gap = (max_price - min_price) / max_price if max_price > 0 else 0
                abs_gap = max_price - min_price

                group_metrics.append({
                    'group_id': group_id,
                    'items': items,
                    'price_gap': price_gap,
                    'abs_gap': abs_gap,
                    'max_price': max_price,
                    'min_price': min_price,
                    'mean_price': mean_price,
                    'size': len(items),
                    'prices': prices
                })

        print(f"  计算完成 {len(group_metrics)} 个组")
        return group_metrics

    def select_by_percentile(
        self,
        group_metrics: List[Dict],
        percentile: float,
        sort_by: str = "price_gap",
        reverse: bool = False
    ) -> List[Dict]:
        """百分位选择（连续区间）"""
        sorted_groups = sorted(group_metrics, key=lambda x: x[sort_by], reverse=reverse)
        num_groups = int(len(sorted_groups) * percentile)
        if num_groups < 1:
            num_groups = 1
        selected = sorted_groups[:num_groups]
        print(f"  百分位 {percentile*100:.0f}%: 选中 {num_groups} 个组")
        return selected

    def select_by_count(
        self,
        group_metrics: List[Dict],
        count: int,
        sort_by: str = "price_gap",
        reverse: bool = False
    ) -> List[Dict]:
        """数量选择（连续区间）"""
        sorted_groups = sorted(group_metrics, key=lambda x: x[sort_by], reverse=reverse)
        selected = sorted_groups[:count]
        print(f"  数量选择: 选中 {len(selected)} 个组")
        return selected

    def select_by_threshold(
        self,
        group_metrics: List[Dict],
        field: str,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None
    ) -> List[Dict]:
        """阈值选择（可以非连续）"""
        selected = []
        for g in group_metrics:
            value = g[field]
            if min_value is not None and value < min_value:
                continue
            if max_value is not None and value > max_value:
                continue
            selected.append(g)

        print(f"  阈值选择 ({field}): ", end="")
        if min_value is not None and max_value is not None:
            print(f"{min_value} ≤ {field} ≤ {max_value}, 选中 {len(selected)} 个组")
        elif min_value is not None:
            print(f"{field} ≥ {min_value}, 选中 {len(selected)} 个组")
        elif max_value is not None:
            print(f"{field} ≤ {max_value}, 选中 {len(selected)} 个组")

        return selected

    def select_by_random(
        self,
        group_metrics: List[Dict],
        count: int,
        seed: Optional[int] = None
    ) -> List[Dict]:
        """随机选择（非连续）"""
        if seed is not None:
            random.seed(seed)

        if count >= len(group_metrics):
            selected = group_metrics.copy()
        else:
            selected = random.sample(group_metrics, count)

        print(f"  随机选择: 选中 {len(selected)} 个组 (seed={seed})")
        return selected

    def select_by_indices(
        self,
        group_metrics: List[Dict],
        indices: List[int],
        sort_by: str = "price_gap",
        reverse: bool = False
    ) -> List[Dict]:
        """按索引选择（非连续，可以跳跃）"""
        sorted_groups = sorted(group_metrics, key=lambda x: x[sort_by], reverse=reverse)
        selected = []
        for idx in indices:
            if 0 <= idx < len(sorted_groups):
                selected.append(sorted_groups[idx])

        print(f"  索引选择: 选中 {len(selected)} 个组 (指定 {len(indices)} 个索引)")
        return selected

    def select_by_group_ids(
        self,
        group_metrics: List[Dict],
        group_ids: List[int]
    ) -> List[Dict]:
        """按组ID选择（非连续）"""
        selected = [g for g in group_metrics if g['group_id'] in group_ids]
        print(f"  组ID选择: 选中 {len(selected)} 个组 (指定 {len(group_ids)} 个ID)")
        return selected

    def select_by_condition(
        self,
        group_metrics: List[Dict],
        condition: Callable[[Dict], bool]
    ) -> List[Dict]:
        """自定义条件选择（最灵活）"""
        selected = [g for g in group_metrics if condition(g)]
        print(f"  自定义条件: 选中 {len(selected)} 个组")
        return selected

    def select_by_multi_conditions(
        self,
        group_metrics: List[Dict],
        conditions: List[Dict],
        logic: str = "AND"
    ) -> List[Dict]:
        """
        多条件组合选择

        Args:
            conditions: 条件列表，每个条件是字典，如:
                {'field': 'price_gap', 'min': 0.2, 'max': 0.5}
                {'field': 'max_price', 'min': 100}
            logic: "AND" 或 "OR"
        """
        selected = []

        for g in group_metrics:
            if logic == "AND":
                match = True
                for cond in conditions:
                    field = cond['field']
                    value = g[field]
                    if 'min' in cond and value < cond['min']:
                        match = False
                        break
                    if 'max' in cond and value > cond['max']:
                        match = False
                        break
                if match:
                    selected.append(g)

            elif logic == "OR":
                match = False
                for cond in conditions:
                    field = cond['field']
                    value = g[field]
                    cond_match = True
                    if 'min' in cond and value < cond['min']:
                        cond_match = False
                    if 'max' in cond and value > cond['max']:
                        cond_match = False
                    if cond_match:
                        match = True
                        break
                if match:
                    selected.append(g)

        print(f"  多条件选择 ({logic}): 选中 {len(selected)} 个组")
        return selected

    def save_dataset(
        self,
        selected_groups: List[Dict],
        output_file: str,
        reindex_groups: bool = True,
        keep_metadata: bool = True
    ) -> Dict:
        """保存数据集"""
        output_path = self.data_dir / output_file

        result = []
        for new_idx, group_info in enumerate(selected_groups):
            for item in group_info['items']:
                item_data = {
                    'folder_id': item['folder_id'],
                    'price': item['price'],
                    'folder_path': item['folder_path'],
                    'group_id': new_idx if reindex_groups else item['group_id']
                }

                # 可选：保留元数据
                if keep_metadata:
                    item_data.update({
                        'original_group_id': group_info['group_id'],
                        'price_gap': group_info['price_gap'],
                        'abs_gap': group_info['abs_gap'],
                        'max_price': group_info['max_price'],
                        'min_price': group_info['min_price']
                    })

                result.append(item_data)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        stats = {
            'file': str(output_path),
            'items': len(result),
            'groups': len(selected_groups),
            'price_gap_range': (
                min(g['price_gap'] for g in selected_groups),
                max(g['price_gap'] for g in selected_groups)
            ) if selected_groups else (0, 0)
        }

        print(f"  ✓ 保存到: {output_file}")
        print(f"    - {stats['items']} 项, {stats['groups']} 组")
        print(f"    - price_gap: {stats['price_gap_range'][0]:.4f} - {stats['price_gap_range'][1]:.4f}")

        return stats


def demo_usage():
    """演示各种用法"""

    generator = AdvancedNearTieGenerator()

    # 加载数据（只加载一次，重复使用）
    data = generator.load_and_merge_sources(["Overall.json"])
    group_metrics = generator.calculate_group_metrics(data)

    print("\n" + "="*80)
    print("演示1: 标准百分位选择（连续）")
    print("="*80)

    # Near-Tie Low: 前20%
    low_20 = generator.select_by_percentile(
        group_metrics,
        percentile=0.2,
        sort_by="price_gap",
        reverse=False
    )
    generator.save_dataset(low_20, "Demo-Low-20pct.json")

    # Near-Tie High: 后20%
    high_20 = generator.select_by_percentile(
        group_metrics,
        percentile=0.2,
        sort_by="price_gap",
        reverse=True
    )
    generator.save_dataset(high_20, "Demo-High-20pct.json")


    print("\n" + "="*80)
    print("演示2: 阈值选择（非连续）")
    print("="*80)

    # 选择price_gap在0.2-0.4之间的组
    mid_range = generator.select_by_threshold(
        group_metrics,
        field="price_gap",
        min_value=0.2,
        max_value=0.4
    )
    generator.save_dataset(mid_range, "Demo-Gap-0.2-0.4.json")

    # 选择max_price大于200的组
    high_price = generator.select_by_threshold(
        group_metrics,
        field="max_price",
        min_value=200
    )
    generator.save_dataset(high_price, "Demo-MaxPrice-Above200.json")


    print("\n" + "="*80)
    print("演示3: 随机选择（非连续）")
    print("="*80)

    # 随机选择50个组
    random_50 = generator.select_by_random(group_metrics, count=50, seed=42)
    generator.save_dataset(random_50, "Demo-Random-50.json")


    print("\n" + "="*80)
    print("演示4: 索引跳跃选择（非连续）")
    print("="*80)

    # 选择第0, 10, 20, 30...个组（每隔10个选一个）
    indices = list(range(0, 100, 10))
    every_10 = generator.select_by_indices(
        group_metrics,
        indices=indices,
        sort_by="price_gap",
        reverse=False
    )
    generator.save_dataset(every_10, "Demo-Every10th.json")


    print("\n" + "="*80)
    print("演示5: 组ID选择（非连续）")
    print("="*80)

    # 选择特定的组ID
    specific_ids = [1, 5, 10, 15, 20, 100, 150, 200, 250]
    specific = generator.select_by_group_ids(group_metrics, group_ids=specific_ids)
    generator.save_dataset(specific, "Demo-SpecificIDs.json")


    print("\n" + "="*80)
    print("演示6: 自定义条件选择（最灵活）")
    print("="*80)

    # 选择price_gap < 0.3 且 组内有6个item的组
    custom = generator.select_by_condition(
        group_metrics,
        condition=lambda g: g['price_gap'] < 0.3 and g['size'] == 6
    )
    generator.save_dataset(custom, "Demo-Custom-Gap30-Size6.json")


    print("\n" + "="*80)
    print("演示7: 多条件组合选择（AND）")
    print("="*80)

    # price_gap在0.3-0.6之间 AND max_price > 100
    multi_and = generator.select_by_multi_conditions(
        group_metrics,
        conditions=[
            {'field': 'price_gap', 'min': 0.3, 'max': 0.6},
            {'field': 'max_price', 'min': 100}
        ],
        logic="AND"
    )
    generator.save_dataset(multi_and, "Demo-Multi-AND.json")


    print("\n" + "="*80)
    print("演示8: 多条件组合选择（OR）")
    print("="*80)

    # price_gap < 0.2 OR price_gap > 0.8
    multi_or = generator.select_by_multi_conditions(
        group_metrics,
        conditions=[
            {'field': 'price_gap', 'max': 0.2},
            {'field': 'price_gap', 'min': 0.8}
        ],
        logic="OR"
    )
    generator.save_dataset(multi_or, "Demo-Multi-OR.json")


    print("\n" + "="*80)
    print("演示9: 数据重复使用 - 生成多个不同百分位的数据集")
    print("="*80)

    # 同一份数据，生成5%, 10%, 15%, 20%, 25%的Near-Tie Low
    for pct in [0.05, 0.10, 0.15, 0.20, 0.25]:
        selected = generator.select_by_percentile(
            group_metrics,
            percentile=pct,
            sort_by="price_gap",
            reverse=False
        )
        generator.save_dataset(selected, f"Demo-Low-{int(pct*100)}pct.json")


    print("\n" + "="*80)
    print("✓ 所有演示完成！")
    print("="*80)
    print("\n数据可以重复使用的示例：")
    print("  - 同一组可以出现在多个数据集中")
    print("  - 可以从同一份group_metrics中选择多次")
    print("  - 支持连续和非连续选择")
    print("  - 支持各种灵活的筛选条件")


if __name__ == "__main__":
    demo_usage()
