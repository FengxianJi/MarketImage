"""
完整的拍卖数据管道
功能：
1. 加载并过滤数据
2. 使用Google Drive ImageId下载对应的主图（一一对应）
3. 保存到benchmark/EmergingArt目录，每个作品一个序号文件夹
"""

import pandas as pd
import requests
import json
import shutil
import time
import statistics
from pathlib import Path

# PIL导入（用于创建占位图）
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class AuctionDataPipeline:
    """拍卖数据处理管道"""

    def __init__(self, data_path=None, output_base_path=None, use_gdrive=True):
        """
        初始化数据管道

        Args:
            data_path: 数据文件路径
            output_base_path: 输出基础路径（EmergingArt目录）
            use_gdrive: 是否使用Google Drive ImageId下载图片（推荐）
        """
        if data_path is None:
            self.data_path = Path(__file__).parent / "data" / "results_2024_05_11.xlsx"
        else:
            self.data_path = Path(data_path)

        if output_base_path is None:
            self.output_base_path = Path("/mnt/data/user/fengxian.ji/AUCTION/benchmark/EmergingArt")
        else:
            self.output_base_path = Path(output_base_path)

        self.data = None
        self.filtered_data = None
        self.use_gdrive = use_gdrive

    def load_data(self):
        """加载数据"""
        print(f"正在加载数据: {self.data_path}")

        if not self.data_path.exists():
            raise FileNotFoundError(f"数据文件不存在: {self.data_path}")

        # 根据文件扩展名选择读取方式
        if self.data_path.suffix == '.xlsx':
            self.data = pd.read_excel(self.data_path, engine='openpyxl')
        elif self.data_path.suffix == '.csv':
            self.data = pd.read_csv(self.data_path)
        elif self.data_path.suffix == '.tab':
            self.data = pd.read_csv(self.data_path, sep='\t')
        else:
            raise ValueError(f"不支持的文件格式: {self.data_path.suffix}")

        print(f"✓ 数据加载成功，共 {len(self.data)} 条记录")
        return self

    def filter_data(self, min_price=10, max_price=200, no_signature=True, max_records=None):
        """
        过滤数据

        Args:
            min_price: 最低价格（包含）
            max_price: 最高价格（包含）
            no_signature: 是否只保留无签名的作品
            max_records: 最大记录数（用于测试）

        Returns:
            self: 链式调用
        """
        if self.data is None:
            raise ValueError("请先调用 load_data() 加载数据")

        print(f"\n开始过滤数据...")
        print(f"过滤条件:")
        print(f"  - 价格范围: [{min_price}, {max_price}]")
        print(f"  - 无签名: {no_signature}")
        if max_records:
            print(f"  - 最大记录数: {max_records}")

        filtered = self.data.copy()
        initial_count = len(filtered)

        # 1. 价格过滤
        filtered = filtered[(filtered['PRICE'] >= min_price) & (filtered['PRICE'] <= max_price)]
        price_filtered = len(filtered)
        print(f"\n✓ 价格过滤: {initial_count} -> {price_filtered} (保留 {price_filtered/initial_count*100:.2f}%)")

        # 2. 签名过滤
        if no_signature:
            filtered['SIGNATURE'] = filtered['SIGNATURE'].fillna('')
            filtered = filtered[filtered['SIGNATURE'].astype(str).str.contains('Not signed', case=False, na=False)]
            signature_filtered = len(filtered)
            if price_filtered > 0:
                print(f"✓ 签名过滤: {price_filtered} -> {signature_filtered} (保留 {signature_filtered/price_filtered*100:.2f}%)")
        else:
            signature_filtered = price_filtered
            print(f"✓ 签名过滤: 已跳过 (允许所有签名类型)")

        # 3. URL过滤 - 已取消，保留所有记录
        # filtered = filtered[filtered['URL'].astype(str).str.contains('http', na=False)]
        url_filtered = len(filtered)
        print(f"✓ URL过滤: 已跳过 (保留所有记录，共 {url_filtered} 条)")

        # 4. 限制记录数（用于测试）
        if max_records and len(filtered) > max_records:
            filtered = filtered.head(max_records)
            print(f"✓ 数量限制: {url_filtered} -> {max_records}")

        self.filtered_data = filtered.reset_index(drop=True)
        print(f"\n过滤完成，最终保留 {len(self.filtered_data)} 条记录")

        return self

    def get_statistics(self):
        """获取过滤后数据的统计信息"""
        if self.filtered_data is None or len(self.filtered_data) == 0:
            print("没有过滤后的数据")
            return self

        print("\n" + "=" * 80)
        print("过滤后数据统计")
        print("=" * 80)

        data = self.filtered_data

        print(f"\n【基本信息】")
        print(f"记录数: {len(data)}")
        print(f"价格范围: {data['PRICE'].min():.2f} - {data['PRICE'].max():.2f}")
        print(f"平均价格: {data['PRICE'].mean():.2f}")

        # 检查ImageId可用性
        if 'ImageId' in data.columns:
            has_imageid = data['ImageId'].notna().sum()
            print(f"有ImageId的记录: {has_imageid} ({has_imageid/len(data)*100:.2f}%)")

        print(f"下载方式: {'Google Drive (ImageId)' if self.use_gdrive else 'Selenium爬取'}")

        print("\n" + "=" * 80)
        return self

    def clear_output_directory(self):
        """清空输出目录中的所有序号文件夹"""
        if not self.output_base_path.exists():
            print(f"输出目录不存在，将创建: {self.output_base_path}")
            self.output_base_path.mkdir(parents=True, exist_ok=True)
            return self

        print(f"\n清理输出目录: {self.output_base_path}")

        # 删除所有数字命名的文件夹
        deleted_count = 0
        for item in self.output_base_path.iterdir():
            if item.is_dir() and item.name.isdigit():
                shutil.rmtree(item)
                deleted_count += 1

        print(f"✓ 已删除 {deleted_count} 个旧的序号文件夹")
        return self

    def download_image_from_gdrive(self, image_id, save_path):
        """
        从Google Drive下载图片

        Args:
            image_id: Google Drive文件ID
            save_path: 保存路径

        Returns:
            bool: 是否成功下载
        """
        if not image_id or pd.isna(image_id):
            return False

        try:
            url = f"https://drive.google.com/uc?id={image_id}&export=download"
            response = requests.get(url, timeout=15, stream=True)

            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
            else:
                return False

        except Exception as e:
            print(f"  下载失败: {str(e)[:50]}")
            return False

    def create_placeholder_image(self, save_path, width=800, height=600):
        """
        创建占位图片（当无法下载真实图片时）

        Args:
            save_path: 保存路径
            width: 图片宽度
            height: 图片高度
        """
        if not PIL_AVAILABLE:
            # PIL不可用，创建一个空文件标记
            save_path.touch()
            return

        try:
            # 创建灰色背景图片
            img = Image.new('RGB', (width, height), color=(200, 200, 200))
            draw = ImageDraw.Draw(img)

            # 添加文字
            text = "Image Not Available"
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
            except:
                font = ImageFont.load_default()

            # 计算文字位置（居中）
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = (width - text_width) // 2
            y = (height - text_height) // 2

            draw.text((x, y), text, fill=(100, 100, 100), font=font)
            img.save(save_path)

        except Exception as e:
            print(f"  创建占位图失败: {e}")
            # 至少创建一个空文件
            save_path.touch()

    def export_to_benchmark(self, download_images=True):
        """
        将过滤后的数据导出到benchmark目录

        Args:
            download_images: 是否下载图片

        Returns:
            self: 链式调用
        """
        if self.filtered_data is None or len(self.filtered_data) == 0:
            print("没有可导出的数据")
            return self

        print(f"\n开始导出数据到: {self.output_base_path}")
        print("=" * 80)

        success_count = 0
        failed_count = 0
        images_downloaded = 0
        images_placeholder = 0

        for idx, row in self.filtered_data.iterrows():
            try:
                # 创建序号文件夹
                item_dir = self.output_base_path / str(idx)
                item_dir.mkdir(parents=True, exist_ok=True)

                figure_dir = item_dir / "figure"
                figure_dir.mkdir(exist_ok=True)

                # 1. 创建description.txt
                description = self._create_description(row)
                desc_file = item_dir / "description.txt"
                desc_file.write_text(description, encoding='utf-8')

                # 2. 创建growth.json
                growth_data = self._create_growth_data(row)
                growth_file = item_dir / "growth.json"
                growth_file.write_text(json.dumps(growth_data, indent=2, ensure_ascii=False), encoding='utf-8')

                # 3. 保存原始Catawiki URL（方便手动核对）
                url = row.get('URL', '')
                if pd.notna(url) and url:
                    url_file = item_dir / "source_url.txt"
                    url_file.write_text(str(url), encoding='utf-8')

                # 4. 下载图片（从Google Drive或创建占位图）
                if download_images:
                    artist = str(row.get('ARTIST', 'Unknown')) if pd.notna(row.get('ARTIST')) else 'Unknown'
                    print(f"[{idx+1}/{len(self.filtered_data)}] 处理: {artist}...")

                    image_id = row.get('ImageId')
                    image_path = figure_dir / "1.jpg"  # 只下载一张主图

                    if self.use_gdrive and pd.notna(image_id):
                        # 从Google Drive下载
                        if self.download_image_from_gdrive(image_id, image_path):
                            print(f"  ✓ 从Google Drive下载图片成功")
                            images_downloaded += 1
                        else:
                            print(f"  创建占位图...")
                            self.create_placeholder_image(image_path)
                            images_placeholder += 1
                    else:
                        # 创建占位图
                        print(f"  无ImageId，创建占位图...")
                        self.create_placeholder_image(image_path)
                        images_placeholder += 1

                success_count += 1

                # 每个作品处理完后暂停，避免被检测为爬虫
                if idx < len(self.filtered_data) - 1:  # 最后一个不需要等待
                    time.sleep(0.5)  # Google Drive下载间隔较短即可

            except Exception as e:
                failed_count += 1
                print(f"✗ 处理记录 {idx} 失败: {str(e)}")
                continue

        print("\n" + "=" * 80)
        print(f"导出完成！")
        print(f"  成功: {success_count} 条")
        print(f"  失败: {failed_count} 条")
        print(f"  真实图片: {images_downloaded} 张")
        print(f"  占位图: {images_placeholder} 个")
        print(f"  输出目录: {self.output_base_path}")
        print("=" * 80)

        return self

    def _create_description(self, row):
        """创建description.txt内容"""
        # 安全获取字段并转换为字符串
        title = str(row.get('TITLE OF ARTWORK', 'Untitled')) if pd.notna(row.get('TITLE OF ARTWORK')) else 'Untitled'
        artist = str(row.get('ARTIST', 'Unknown Artist')) if pd.notna(row.get('ARTIST')) else 'Unknown Artist'
        technique = str(row.get('TECHNIQUE', 'Unknown')) if pd.notna(row.get('TECHNIQUE')) else 'Unknown'
        year = str(row.get('YEAR', 'N/A')) if pd.notna(row.get('YEAR')) else 'N/A'
        condition = str(row.get('CONDITION', 'N/A')) if pd.notna(row.get('CONDITION')) else 'N/A'
        dimensions = str(row.get('TOTAL DIMENSIONS', 'N/A')) if pd.notna(row.get('TOTAL DIMENSIONS')) else 'N/A'
        description_text = str(row.get('DESCRIPTION', '')) if pd.notna(row.get('DESCRIPTION')) else 'No description available.'
        url = str(row.get('URL', '')) if pd.notna(row.get('URL')) else 'N/A'
        signature = str(row.get('SIGNATURE', 'N/A')) if pd.notna(row.get('SIGNATURE')) else 'N/A'

        desc = f"""Title: {title}

Artist: {artist}
Year: {year}
Technique: {technique}
Dimensions: {dimensions}
Condition: {condition}

Description:
{description_text}

Category: Art - Prints
Signature: {signature}

Source: {url}
"""
        return desc

    def _create_growth_data(self, row):
        """创建growth.json内容"""
        price = row.get('PRICE', 0)
        estimation = str(row.get('ESTIMATION', '')) if pd.notna(row.get('ESTIMATION')) else 'N/A'
        auction_date = str(row.get('AUCTION DATE', 'N/A')) if pd.notna(row.get('AUCTION DATE')) else 'N/A'

        growth_data = {
            "final_price": f"€{price:.0f}",
            "estimation": estimation,
            "auction_date": auction_date,
            "price_numeric": float(price)
        }

        return growth_data

    def get_filtered_data(self):
        """获取过滤后的数据"""
        return self.filtered_data

    def create_price_groups_with_data_json(self, group_size=6, num_groups_per_price=2,
                                           seed_low=42, seed_mid=43, seed_high=44,
                                           seed_sample_low=45, seed_sample_mid=46, seed_sample_high=47):
        """
        按价格将数据分成3个价格区间，每个区间分组并生成data/目录下的JSON文件
        参考 EmergingArt_test100 的结构和 generation_testv1.py 的逻辑

        流程：
        1. 加载所有项目的价格数据
        2. 按价格三等分：Low-price、Mid-price、High-price
        3. 每个价格区间内分组（每组group_size个）
        4. 从每个价格区间抽取num_groups_per_price个组
        5. 生成4个JSON文件：Low-price.json、Mid-price.json、High-price.json、Overall.json

        Args:
            group_size: 每组的项目数量（默认6）
            num_groups_per_price: 每个价格区间抽取的组数（默认2）
            seed_low/mid/high: 各价格区间分组的随机种子
            seed_sample_low/mid/high: 各价格区间抽样的随机种子

        Returns:
            dict: 包含划分信息的字典
        """
        import random

        if not self.output_base_path.exists():
            print("输出目录不存在，请先导出数据")
            return None

        print("\n" + "="*80)
        print("按价格分组生成data目录JSON文件（参考generation_testv1.py逻辑）")
        print("="*80)

        # 1. 加载所有项目的价格数据
        print("\n步骤 1: 加载所有项目的价格数据")
        items = []
        for subdir in self.output_base_path.iterdir():
            if subdir.is_dir() and subdir.name.isdigit():
                growth_file = subdir / "growth.json"
                if growth_file.exists():
                    try:
                        with open(growth_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        items.append({
                            'folder_id': subdir.name,
                            'price': data.get('price_numeric', 0),
                            'folder_path': str(subdir)
                        })
                    except Exception as e:
                        print(f"  警告: 读取 {growth_file} 失败: {e}")

        if not items:
            print("未找到任何数据")
            return None

        print(f"共加载 {len(items)} 个项目")

        # 2. 按价格使用方案三的最优分割点划分
        print("\n步骤 2: 按价格分成三个区间（使用方案三的最优分割算法）")
        sorted_items = sorted(items, key=lambda x: x['price'])

        # 使用方案三的最优分割算法
        n = len(sorted_items)
        total_value = sum(item['price'] for item in sorted_items)

        print(f"  正在计算最优分割点...")
        split_result = self._find_optimal_splits_for_items(sorted_items, total_value / 3)

        split1 = split_result['split1']
        split2 = split_result['split2']

        low_price_items = sorted_items[:split1]
        mid_price_items = sorted_items[split1:split2]
        high_price_items = sorted_items[split2:]

        print(f"\n价格区间划分（方案三最优分割）:")
        print(f"Low-price:  {len(low_price_items):4d} items ({len(low_price_items)/n*100:5.1f}%), 价格范围: €{low_price_items[0]['price']:.2f} - €{low_price_items[-1]['price']:.2f}, 总金额: €{sum(i['price'] for i in low_price_items):.2f}")
        print(f"Mid-price:  {len(mid_price_items):4d} items ({len(mid_price_items)/n*100:5.1f}%), 价格范围: €{mid_price_items[0]['price']:.2f} - €{mid_price_items[-1]['price']:.2f}, 总金额: €{sum(i['price'] for i in mid_price_items):.2f}")
        print(f"High-price: {len(high_price_items):4d} items ({len(high_price_items)/n*100:5.1f}%), 价格范围: €{high_price_items[0]['price']:.2f} - €{high_price_items[-1]['price']:.2f}, 总金额: €{sum(i['price'] for i in high_price_items):.2f}")

        print(f"\n价格分界点:")
        print(f"  Low-price ≤ €{low_price_items[-1]['price']:.0f}")
        print(f"  €{low_price_items[-1]['price']:.0f} < Mid-price ≤ €{mid_price_items[-1]['price']:.0f}")
        print(f"  High-price > €{mid_price_items[-1]['price']:.0f}")

        # 3. 对每个区间进行分组
        print("\n步骤 3: 对每个价格区间进行分组")

        def group_by_seed(items_list, grp_size, seed):
            """按随机种子分组"""
            random.seed(seed)
            shuffled = items_list.copy()
            random.shuffle(shuffled)

            groups = []
            for i in range(0, len(shuffled), grp_size):
                group = shuffled[i:i+grp_size]
                # 如果剩余的小于2个，丢弃
                if len(group) < 2:
                    print(f"    丢弃 {len(group)} 个孤立项")
                    break
                groups.append(group)
            return groups

        print(f"\nLow-price 区间分组（每组{group_size}个，种子={seed_low}）:")
        low_groups = group_by_seed(low_price_items, group_size, seed_low)
        print(f"  生成 {len(low_groups)} 个组")

        print(f"\nMid-price 区间分组（每组{group_size}个，种子={seed_mid}）:")
        mid_groups = group_by_seed(mid_price_items, group_size, seed_mid)
        print(f"  生成 {len(mid_groups)} 个组")

        print(f"\nHigh-price 区间分组（每组{group_size}个，种子={seed_high}）:")
        high_groups = group_by_seed(high_price_items, group_size, seed_high)
        print(f"  生成 {len(high_groups)} 个组")

        # 4. 从每个区间抽取指定数量的组
        print(f"\n步骤 4: 从每个价格区间抽取{num_groups_per_price}个组")

        def sample_groups(groups, num, seed):
            """从分组中随机抽取指定数量的组"""
            if num is None:
                # None表示使用全部组
                return groups
            random.seed(seed)
            if len(groups) <= num:
                return groups
            return random.sample(groups, num)

        print(f"\nLow-price 抽取（种子={seed_sample_low}）:")
        low_sampled = sample_groups(low_groups, num_groups_per_price, seed_sample_low)
        print(f"  抽取 {len(low_sampled)} 个组")

        print(f"\nMid-price 抽取（种子={seed_sample_mid}）:")
        mid_sampled = sample_groups(mid_groups, num_groups_per_price, seed_sample_mid)
        print(f"  抽取 {len(mid_sampled)} 个组")

        print(f"\nHigh-price 抽取（种子={seed_sample_high}）:")
        high_sampled = sample_groups(high_groups, num_groups_per_price, seed_sample_high)
        print(f"  抽取 {len(high_sampled)} 个组")

        # 5. 生成4个JSON文件
        print("\n步骤 5: 生成data目录下的JSON文件")

        # 创建data目录
        data_dir = self.output_base_path / "data"
        data_dir.mkdir(exist_ok=True)

        def create_json_from_groups(groups, output_path, json_name):
            """从分组创建JSON文件"""
            result = []
            for group_idx, group in enumerate(groups):
                # 过滤掉只有1个项目的孤立组
                if len(group) < 2:
                    print(f"    筛选掉孤立组 (只有1个项目)")
                    continue

                for item in group:
                    result.append({
                        'folder_id': item['folder_id'],
                        'price': item['price'],
                        'folder_path': item['folder_path'],
                        'group_id': group_idx
                    })

            # 保存JSON文件
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            print(f"  ✓ {json_name}: 共 {len(result)} 个项目, {len(groups)} 个组")
            return result

        # 生成Overall.json（所有价格区间合并）
        print("\n生成 Overall.json:")
        overall_groups = low_sampled + mid_sampled + high_sampled
        overall_path = data_dir / "Overall.json"
        overall_result = create_json_from_groups(overall_groups, overall_path, "Overall.json")

        # 生成Low-price.json
        print("\n生成 Low-price.json:")
        low_path = data_dir / "Low-price.json"
        low_result = create_json_from_groups(low_sampled, low_path, "Low-price.json")

        # 生成Mid-price.json
        print("\n生成 Mid-price.json:")
        mid_path = data_dir / "Mid-price.json"
        mid_result = create_json_from_groups(mid_sampled, mid_path, "Mid-price.json")

        # 生成High-price.json
        print("\n生成 High-price.json:")
        high_path = data_dir / "High-price.json"
        high_result = create_json_from_groups(high_sampled, high_path, "High-price.json")

        # 统计信息
        print("\n" + "="*80)
        print("生成完成")
        print("="*80)
        print(f"\ndata目录位置: {data_dir}")
        print(f"\n生成的JSON文件:")
        print(f"  - Low-price.json:  {len(low_result)} 个项目")
        print(f"  - Mid-price.json:  {len(mid_result)} 个项目")
        print(f"  - High-price.json: {len(high_result)} 个项目")
        print(f"  - Overall.json:    {len(overall_result)} 个项目")

        return {
            'data_dir': str(data_dir),
            'low_price': {
                'count': len(low_result),
                'groups': len(low_sampled),
                'price_range': [low_price_items[0]['price'], low_price_items[-1]['price']]
            },
            'mid_price': {
                'count': len(mid_result),
                'groups': len(mid_sampled),
                'price_range': [mid_price_items[0]['price'], mid_price_items[-1]['price']]
            },
            'high_price': {
                'count': len(high_result),
                'groups': len(high_sampled),
                'price_range': [high_price_items[0]['price'], high_price_items[-1]['price']]
            },
            'overall': {
                'count': len(overall_result),
                'groups': len(overall_groups)
            }
        }

    def _find_optimal_splits_for_items(self, sorted_items, target_value):
        """
        找到最优的分割点，使得金额和数量都尽量均衡
        适配items格式（包含folder_id, price, folder_path字段）

        Args:
            sorted_items: 按价格排序的作品列表
            target_value: 目标金额（总金额的1/3）

        Returns:
            dict: 包含最优分割点的字典
        """
        total_items = len(sorted_items)
        total_value = sum(item['price'] for item in sorted_items)

        best_score = float('inf')
        best_split1, best_split2 = 0, 0

        # 在合理范围内搜索最优分割点
        for split1 in range(int(total_items * 0.25), int(total_items * 0.45)):
            for split2 in range(int(total_items * 0.55), int(total_items * 0.75)):
                group1 = sorted_items[:split1]
                group2 = sorted_items[split1:split2]
                group3 = sorted_items[split2:]

                sum1 = sum(item['price'] for item in group1)
                sum2 = sum(item['price'] for item in group2)
                sum3 = sum(item['price'] for item in group3)

                # 计算金额和数量的标准差
                value_std = statistics.stdev([sum1, sum2, sum3])
                count_std = statistics.stdev([len(group1), len(group2), len(group3)])

                # 综合评分（金额权重更高）
                score = value_std * 2 + count_std * (total_value / total_items)

                if score < best_score:
                    best_score = score
                    best_split1 = split1
                    best_split2 = split2

        return {
            'split1': best_split1,
            'split2': best_split2
        }

    def _find_optimal_splits(self, sorted_items, target_value):
        """
        找到最优的分割点，使得金额和数量都尽量均衡

        Args:
            sorted_items: 按价格排序的作品列表
            target_value: 目标金额（总金额的1/3）

        Returns:
            dict: 包含最优分割点的字典
        """
        total_items = len(sorted_items)
        total_value = sum(item['price'] for item in sorted_items)

        best_score = float('inf')
        best_split1, best_split2 = 0, 0

        # 在合理范围内搜索最优分割点
        for split1 in range(int(total_items * 0.25), int(total_items * 0.45)):
            for split2 in range(int(total_items * 0.55), int(total_items * 0.75)):
                group1 = sorted_items[:split1]
                group2 = sorted_items[split1:split2]
                group3 = sorted_items[split2:]

                sum1 = sum(item['price'] for item in group1)
                sum2 = sum(item['price'] for item in group2)
                sum3 = sum(item['price'] for item in group3)

                # 计算金额和数量的标准差
                value_std = statistics.stdev([sum1, sum2, sum3])
                count_std = statistics.stdev([len(group1), len(group2), len(group3)])

                # 综合评分（金额权重更高）
                score = value_std * 2 + count_std * (total_value / total_items)

                if score < best_score:
                    best_score = score
                    best_split1 = split1
                    best_split2 = split2

        return {
            'split1': best_split1,
            'split2': best_split2
        }


    def create_near_tie_low_dataset(self, source_json="Overall.json", percentile=0.2):
        """
        生成Near-Tie Low数据集 - 组内价格差距最小的组

        选择组内价格差距最小的 percentile% 组，这些组内所有项目价格非常接近，
        模型难以区分，适合测试模型在困难样本上的表现。

        差距指标 = (max_price - min_price) / max_price

        Args:
            source_json: 源数据JSON文件名（默认"Overall.json"）
            percentile: 选择的百分比（默认0.2，即20%）

        Returns:
            dict: 包含生成信息的字典
        """
        data_dir = self.output_base_path / "data"
        source_path = data_dir / source_json

        if not source_path.exists():
            print(f"错误: 源数据文件不存在 {source_path}")
            return None

        print("\n" + "="*80)
        print("生成Near-Tie Low数据集（组内价格差距最小）")
        print("="*80)

        # 1. 加载源数据
        print(f"\n步骤 1: 加载源数据 {source_json}")
        with open(source_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"共加载 {len(data)} 个项目")

        # 2. 按group_id分组
        print(f"\n步骤 2: 按group_id分组")
        groups = {}
        for item in data:
            group_id = item['group_id']
            if group_id not in groups:
                groups[group_id] = []
            groups[group_id].append(item)
        print(f"共 {len(groups)} 个组")

        # 3. 计算每组的价格差距
        print(f"\n步骤 3: 计算每组的价格差距")
        group_metrics = []
        for group_id, items in groups.items():
            prices = [item['price'] for item in items]
            if len(prices) >= 2:
                max_price = max(prices)
                min_price = min(prices)
                price_gap = (max_price - min_price) / max_price if max_price > 0 else 0
                abs_gap = max_price - min_price

                group_metrics.append({
                    'group_id': group_id,
                    'items': items,
                    'price_gap': price_gap,
                    'abs_gap': abs_gap,
                    'max_price': max_price,
                    'min_price': min_price,
                    'size': len(items),
                    'prices': prices
                })
        print(f"  成功计算 {len(group_metrics)} 个组的价格差距")

        # 4. 选择价格差距最小的组
        print(f"\n步骤 4: 选择价格差距最小的 {percentile*100:.0f}% 组")
        sorted_groups = sorted(group_metrics, key=lambda x: x['price_gap'])
        num_groups = int(len(sorted_groups) * percentile)
        if num_groups < 1:
            num_groups = 1
        near_tie_low_groups = sorted_groups[:num_groups]
        print(f"  选择 {num_groups} 个组")

        # 5. 生成Near-Tie-low.json
        print(f"\n步骤 5: 生成Near-Tie-low.json")
        near_tie_low_path = data_dir / "Near-Tie-low.json"

        low_result = []
        for idx, group_info in enumerate(near_tie_low_groups):
            for item in group_info['items']:
                low_result.append({
                    'folder_id': item['folder_id'],
                    'price': item['price'],
                    'folder_path': item['folder_path'],
                    'group_id': idx,
                    'original_group_id': group_info['group_id'],
                    'price_gap': group_info['price_gap'],
                    'abs_gap': group_info['abs_gap']
                })

        with open(near_tie_low_path, 'w', encoding='utf-8') as f:
            json.dump(low_result, f, indent=2, ensure_ascii=False)

        print(f"  ✓ {near_tie_low_path}")
        print(f"    项目数: {len(low_result)}, 组数: {len(near_tie_low_groups)}")

        # 6. 统计信息
        print("\n" + "="*80)
        print("Near-Tie Low数据集生成完成")
        print("="*80)
        print(f"\nNear-Tie Low（最难区分）:")
        print(f"  price_gap 范围: {near_tie_low_groups[0]['price_gap']:.6f} ({near_tie_low_groups[0]['price_gap']*100:.2f}%) - {near_tie_low_groups[-1]['price_gap']:.6f} ({near_tie_low_groups[-1]['price_gap']*100:.2f}%)")
        print(f"  前5组详情:")
        for i, g in enumerate(near_tie_low_groups[:5]):
            print(f"    组 {i}: gap={g['price_gap']:.4f} ({g['price_gap']*100:.1f}%), "
                  f"max=€{g['max_price']:.0f}, min=€{g['min_price']:.0f}, 差=€{g['abs_gap']:.0f}")
            print(f"         价格: {sorted(g['prices'], reverse=True)}")

        return {
            'file': str(near_tie_low_path),
            'items': len(low_result),
            'groups': len(near_tie_low_groups),
            'price_gap_range': [near_tie_low_groups[0]['price_gap'], near_tie_low_groups[-1]['price_gap']]
        }

    def create_near_tie_high_dataset(self, source_json="Overall.json", percentile=0.2):
        """
        生成Near-Tie High数据集 - 组内价格差距最大的组

        选择组内价格差距最大的 percentile% 组，这些组内项目价格差异明显，
        模型容易区分，适合作为基准测试。

        差距指标 = (max_price - min_price) / max_price

        Args:
            source_json: 源数据JSON文件名（默认"Overall.json"）
            percentile: 选择的百分比（默认0.2，即20%）

        Returns:
            dict: 包含生成信息的字典
        """
        data_dir = self.output_base_path / "data"
        source_path = data_dir / source_json

        if not source_path.exists():
            print(f"错误: 源数据文件不存在 {source_path}")
            return None

        print("\n" + "="*80)
        print("生成Near-Tie High数据集（组内价格差距最大）")
        print("="*80)

        # 1. 加载源数据
        print(f"\n步骤 1: 加载源数据 {source_json}")
        with open(source_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"共加载 {len(data)} 个项目")

        # 2. 按group_id分组
        print(f"\n步骤 2: 按group_id分组")
        groups = {}
        for item in data:
            group_id = item['group_id']
            if group_id not in groups:
                groups[group_id] = []
            groups[group_id].append(item)
        print(f"共 {len(groups)} 个组")

        # 3. 计算每组的价格差距
        print(f"\n步骤 3: 计算每组的价格差距")
        group_metrics = []
        for group_id, items in groups.items():
            prices = [item['price'] for item in items]
            if len(prices) >= 2:
                max_price = max(prices)
                min_price = min(prices)
                price_gap = (max_price - min_price) / max_price if max_price > 0 else 0
                abs_gap = max_price - min_price

                group_metrics.append({
                    'group_id': group_id,
                    'items': items,
                    'price_gap': price_gap,
                    'abs_gap': abs_gap,
                    'max_price': max_price,
                    'min_price': min_price,
                    'size': len(items),
                    'prices': prices
                })
        print(f"  成功计算 {len(group_metrics)} 个组的价格差距")

        # 4. 选择价格差距最大的组
        print(f"\n步骤 4: 选择价格差距最大的 {percentile*100:.0f}% 组")
        sorted_groups = sorted(group_metrics, key=lambda x: x['price_gap'], reverse=True)
        num_groups = int(len(sorted_groups) * percentile)
        if num_groups < 1:
            num_groups = 1
        near_tie_high_groups = sorted_groups[:num_groups]
        print(f"  选择 {num_groups} 个组")

        # 5. 生成Near-Tie-high.json
        print(f"\n步骤 5: 生成Near-Tie-high.json")
        near_tie_high_path = data_dir / "Near-Tie-high.json"

        high_result = []
        for idx, group_info in enumerate(near_tie_high_groups):
            for item in group_info['items']:
                high_result.append({
                    'folder_id': item['folder_id'],
                    'price': item['price'],
                    'folder_path': item['folder_path'],
                    'group_id': idx,
                    'original_group_id': group_info['group_id'],
                    'price_gap': group_info['price_gap'],
                    'abs_gap': group_info['abs_gap']
                })

        with open(near_tie_high_path, 'w', encoding='utf-8') as f:
            json.dump(high_result, f, indent=2, ensure_ascii=False)

        print(f"  ✓ {near_tie_high_path}")
        print(f"    项目数: {len(high_result)}, 组数: {len(near_tie_high_groups)}")

        # 6. 统计信息
        print("\n" + "="*80)
        print("Near-Tie High数据集生成完成")
        print("="*80)
        print(f"\nNear-Tie High（最容易区分）:")
        print(f"  price_gap 范围: {near_tie_high_groups[0]['price_gap']:.6f} ({near_tie_high_groups[0]['price_gap']*100:.2f}%) - {near_tie_high_groups[-1]['price_gap']:.6f} ({near_tie_high_groups[-1]['price_gap']*100:.2f}%)")
        print(f"  前5组详情:")
        for i, g in enumerate(near_tie_high_groups[:5]):
            print(f"    组 {i}: gap={g['price_gap']:.4f} ({g['price_gap']*100:.1f}%), "
                  f"max=€{g['max_price']:.0f}, min=€{g['min_price']:.0f}, 差=€{g['abs_gap']:.0f}")
            print(f"         价格: {sorted(g['prices'], reverse=True)}")

        return {
            'file': str(near_tie_high_path),
            'items': len(high_result),
            'groups': len(near_tie_high_groups),
            'price_gap_range': [near_tie_high_groups[0]['price_gap'], near_tie_high_groups[-1]['price_gap']]
        }

    def create_near_tie_dataset(self, source_json="Overall.json", percentile=0.2):
        """
        生成Near-Tie数据集 - 同时生成 Low 和 High 两个数据集

        这是一个便捷方法，会调用 create_near_tie_low_dataset 和 create_near_tie_high_dataset
        分别生成两个数据集。

        Args:
            source_json: 源数据JSON文件名（默认"Overall.json"）
            percentile: 选择的百分比（默认0.2，即20%）

        Returns:
            dict: 包含两个数据集生成信息的字典
        """
        print("\n" + "="*80)
        print("生成Near-Tie数据集（Low + High）")
        print("="*80)

        # 生成 Near-Tie Low
        low_result = self.create_near_tie_low_dataset(source_json, percentile)

        # 生成 Near-Tie High
        high_result = self.create_near_tie_high_dataset(source_json, percentile)

        return {
            'source_json': source_json,
            'percentile': percentile,
            'near_tie_low': low_result,
            'near_tie_high': high_result
        }


# todo


def main():
    """主函数"""
    print("=" * 80)
    print("拍卖数据完整管道 (Google Drive版本 + 按价格分组生成data/JSON)")
    print("=" * 80)

    # 配置参数
    MIN_PRICE = 10
    MAX_PRICE = 1000
    NO_SIGNATURE = True  # True = 只保留无签名作品
    MAX_RECORDS = None  # None表示处理全部数据
    ENABLE_PRICE_GROUPING = True  # 是否启用价格分组
    GROUP_SIZE = 6  # 每组的项目数量
    NUM_GROUPS_PER_PRICE = None  # None = 使用全部组（不抽样）

    # Near-Tie数据集配置
    ENABLE_NEAR_TIE = True  # 是否启用Near-Tie数据集生成
    NEAR_TIE_SOURCE = "Overall.json"  # 源数据文件
    NEAR_TIE_PERCENTILE = 0.2  # 选择的百分比（0.2 = 20%）

    print(f"\n配置:")
    print(f"  价格范围: {MIN_PRICE}-{MAX_PRICE}")
    print(f"  无签名: {NO_SIGNATURE}")
    print(f"  测试记录数: {MAX_RECORDS}")
    print(f"  下载方式: Google Drive (ImageId)")
    print(f"  价格分组: {'启用 (方案三最优分割 + 分组抽样)' if ENABLE_PRICE_GROUPING else '禁用'}")
    if ENABLE_PRICE_GROUPING:
        print(f"    - 每组项目数: {GROUP_SIZE}")
        print(f"    - 每价格区间抽取: {NUM_GROUPS_PER_PRICE} 个组")
    print(f"  Near-Tie数据集: {'启用' if ENABLE_NEAR_TIE else '禁用'}")
    if ENABLE_NEAR_TIE:
        print(f"    - 源数据: {NEAR_TIE_SOURCE}")
        print(f"    - 选择百分比: {NEAR_TIE_PERCENTILE*100:.0f}%")
        print(f"    - 基于组内整体价格差距: (max_price - min_price) / max_price")

    # 创建管道实例
    pipeline = AuctionDataPipeline(use_gdrive=True)

    try:
        # 执行完整流程
        pipeline.load_data() \
                .filter_data(min_price=MIN_PRICE, max_price=MAX_PRICE,
                           no_signature=NO_SIGNATURE, max_records=MAX_RECORDS) \
                .get_statistics() \
                .clear_output_directory() \
                .export_to_benchmark(download_images=True)

        # 如果启用价格分组，则生成data/目录下的JSON文件
        if ENABLE_PRICE_GROUPING:
            print("\n" + "=" * 80)
            print("开始按价格分组生成data/目录JSON文件...")
            print("=" * 80)
            pipeline.create_price_groups_with_data_json(
                group_size=GROUP_SIZE,
                num_groups_per_price=NUM_GROUPS_PER_PRICE
            )

        # 如果启用Near-Tie数据集，则生成Near-Tie.json
        if ENABLE_NEAR_TIE:
            print("\n" + "=" * 80)
            print("开始生成Near-Tie数据集...")
            print("=" * 80)
            pipeline.create_near_tie_dataset(
                source_json=NEAR_TIE_SOURCE,
                percentile=NEAR_TIE_PERCENTILE
            )

        print("\n" + "=" * 80)
        print("✓ 数据管道执行完成！")
        print("=" * 80)

    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
