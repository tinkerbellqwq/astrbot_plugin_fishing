import random
import threading
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date, timedelta
from .db import FishingDB
from astrbot.api import logger

class FishingService:
    def __init__(self, db_path: str):
        """初始化钓鱼服务"""
        self.db = FishingDB(db_path)
        self.auto_fishing_thread = None
        self.auto_fishing_running = False
        self.achievement_check_thread = None
        self.achievement_check_running = False
        
        # 设置日志记录器
        self.LOG = logger
        
        # 确保必要的基础数据存在
        self._ensure_shop_items_exist()
        
        # 启动自动钓鱼
        self.start_auto_fishing_task()
        
        # 启动成就检查
        self.start_achievement_check_task()
        
    def _ensure_shop_items_exist(self):
        """确保商店中有基本物品数据"""
        # 检查是否有鱼竿数据
        rods = self.db.get_all_rods()
        if not rods:
            self.LOG.info("正在初始化基础鱼竿数据...")
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                # 添加几种基本鱼竿
                cursor.executemany("""
                    INSERT OR IGNORE INTO rods (
                        name, description, rarity, source, purchase_cost, 
                        bonus_fish_quality_modifier, bonus_fish_quantity_modifier, 
                        bonus_rare_fish_chance, durability
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    ("简易木竿", "最基础的钓鱼竿，适合入门", 1, "shop", 100, 1.0, 1.0, 0.0, 100),
                    ("优质钓竿", "中级钓鱼竿，提高鱼的质量", 2, "shop", 500, 1.2, 1.0, 0.01, 200),
                    ("专业碳素竿", "高级钓鱼竿，提高钓到稀有鱼的几率", 3, "shop", 1500, 1.3, 1.1, 0.03, 300),
                    ("抗压合金钓竿", "稀有钓鱼竿，综合属性较好", 4, "shop", 5000, 1.4, 1.2, 0.05, 500)
                ])
                conn.commit()
                self.LOG.info("基础鱼竿数据初始化完成。")
        
        # 这里还可以检查其他必要的物品数据，如鱼饵等

    def register(self, user_id: str, nickname: str) -> Dict:
        """注册用户"""
        if self.db.check_user_registered(user_id):
            return {"success": False, "message": "用户已注册"}
        
        success = self.db.register_user(user_id, nickname)
        if success:
            return {"success": True, "message": f"用户 {nickname} 注册成功"}
        else:
            return {"success": False, "message": "注册失败，请稍后再试"}

    def is_registered(self, user_id: str) -> bool:
        """检查用户是否已注册"""
        return self.db.check_user_registered(user_id)
    
    def _check_registered_or_return(self, user_id: str) -> Optional[Dict]:
        """检查用户是否已注册，未注册返回错误信息"""
        if not self.is_registered(user_id):
            return {"success": False, "message": "请先注册才能使用此功能"}
        return None

    def fish(self, user_id: str, is_auto: bool = False) -> Dict:
        """进行一次钓鱼，考虑鱼饵的影响"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 如果是自动钓鱼，先扣除钓鱼成本
        if is_auto:
            fishing_cost = self.get_fishing_cost()
            if not self.db.update_user_coins(user_id, -fishing_cost):
                return {"success": False, "message": "金币不足，无法进行自动钓鱼"}

        # 获取装备信息计算成功率和加成
        equipment = self.db.get_user_equipment(user_id)
        
        # 获取用户当前使用的鱼饵信息
        current_bait = self.db.get_user_current_bait(user_id)
        
        # 如果用户没有主动使用鱼饵，尝试随机消耗一个一次性鱼饵
        consumed_bait = None
        if not current_bait:
            # 获取用户所有可用的一次性鱼饵
            disposable_baits = self.db.get_user_disposable_baits(user_id)
            if disposable_baits:
                # 随机选择一个鱼饵消耗
                random_bait = random.choice(disposable_baits)
                bait_id = random_bait['bait_id']
                if self.db.consume_bait(user_id, bait_id):
                    consumed_bait = random_bait
        
        # 计算钓鱼成功率和加成
        base_success_rate = 0.7
        quality_modifier = 1.0
        quantity_modifier = 1.0 
        rare_chance = 0.0
        garbage_reduction = 0.0
        
        # 应用装备加成（现在equipment总是有值，且各属性也都有默认值）
        rod_quality = equipment.get('rod_quality_modifier', 1.0)
        rod_quantity = equipment.get('rod_quantity_modifier', 1.0)
        rod_rare = equipment.get('rod_rare_chance', 0.0)
        acc_quality = equipment.get('acc_quality_modifier', 1.0)
        acc_quantity = equipment.get('acc_quantity_modifier', 1.0)
        acc_rare = equipment.get('acc_rare_chance', 0.0)
        
        # 应用装备影响
        quality_modifier = rod_quality * acc_quality
        quantity_modifier = rod_quantity * acc_quantity
        rare_chance = rod_rare + acc_rare
        
        # 考虑饰品的特殊效果
        equipped_accessory = self.db.get_user_equipped_accessory(user_id)
        if equipped_accessory:
            # 使用饰品的实际属性值进行加成
            acc_quality_bonus = equipped_accessory.get('bonus_fish_quality_modifier', 1.0)
            acc_quantity_bonus = equipped_accessory.get('bonus_fish_quantity_modifier', 1.0)
            acc_rare_bonus = equipped_accessory.get('bonus_rare_fish_chance', 0.0)
            acc_coin_bonus = equipped_accessory.get('bonus_coin_modifier', 1.0)
            
            # 应用饰品属性到钓鱼相关的修饰符
            quality_modifier *= acc_quality_bonus
            quantity_modifier *= acc_quantity_bonus  
            rare_chance += acc_rare_bonus
            
            # 如果有饰品特殊效果描述，可考虑额外加成
            other_bonus = equipped_accessory.get('other_bonus_description', '')
            # 确保other_bonus是字符串
            other_bonus = str(other_bonus) if other_bonus is not None else ""
            if '减少垃圾' in other_bonus or '减少钓鱼等待时间' in other_bonus:
                garbage_reduction += 0.2
        
        # 应用鱼饵效果（这里简化处理，实际可根据鱼饵类型设置不同效果）
        bait_effect = ""
        
        # 处理主动使用的鱼饵
        if current_bait:
            # 解析鱼饵效果（示例）
            effect_desc = current_bait.get('effect_description', '').lower()
            
            # 简单规则匹配不同效果
            if '提高所有鱼种上钩率' in effect_desc:
                base_success_rate += 0.1
                bait_effect = "提高钓鱼成功率"
            elif '显著提高中大型海鱼上钩率' in effect_desc:
                base_success_rate += 0.05
                rare_chance += 0.03
                bait_effect = "提高稀有鱼几率"
            elif '降低钓上' in effect_desc and '垃圾' in effect_desc:
                garbage_reduction = 0.5
                bait_effect = "降低垃圾概率"
            elif '提高 rarity 3及以上鱼的上钩率' in effect_desc:
                rare_chance += 0.05
                bait_effect = "提高稀有鱼几率"
            elif '钓上的鱼基础价值+10%' in effect_desc:
                quality_modifier *= 1.1
                bait_effect = "提高鱼价值10%"
            elif '下一次钓鱼必定获得双倍数量' in effect_desc:
                quantity_modifier *= 2
                bait_effect = "双倍鱼获取"
                # 这种一次性效果使用后应清除
                self.db.clear_user_current_bait(user_id)
            
            # 拟饵类型不消耗
            if not ('无消耗' in effect_desc):
                # 如果是持续时间类型的鱼饵，则不在这里清除，由get_user_current_bait自动判断
                if current_bait.get('duration_minutes', 0) == 0:
                    # 一般鱼饵用一次就消耗完
                    self.db.clear_user_current_bait(user_id)
        
        # 处理自动消耗的一次性鱼饵
        elif consumed_bait:
            effect_desc = consumed_bait.get('effect_description', '').lower()
            
            # 应用与主动使用相同的效果逻辑
            if '提高所有鱼种上钩率' in effect_desc:
                base_success_rate += 0.1
                bait_effect = f"自动使用【{consumed_bait['name']}】，提高钓鱼成功率"
            elif '显著提高中大型海鱼上钩率' in effect_desc:
                base_success_rate += 0.05
                rare_chance += 0.03
                bait_effect = f"自动使用【{consumed_bait['name']}】，提高稀有鱼几率"
            elif '降低钓上' in effect_desc and '垃圾' in effect_desc:
                garbage_reduction = 0.5
                bait_effect = f"自动使用【{consumed_bait['name']}】，降低垃圾概率"
            elif '提高 rarity 3及以上鱼的上钩率' in effect_desc:
                rare_chance += 0.05
                bait_effect = f"自动使用【{consumed_bait['name']}】，提高稀有鱼几率"
            elif '钓上的鱼基础价值+10%' in effect_desc:
                quality_modifier *= 1.1
                bait_effect = f"自动使用【{consumed_bait['name']}】，提高鱼价值10%"
            elif '下一次钓鱼必定获得双倍数量' in effect_desc:
                quantity_modifier *= 2
                bait_effect = f"自动使用【{consumed_bait['name']}】，双倍鱼获取"
            else:
                bait_effect = f"自动使用【{consumed_bait['name']}】"
        
        # 应用成功率上限
        base_success_rate = min(0.98, base_success_rate)
        
        # 判断是否钓到鱼
        if random.random() < base_success_rate:
            # 确定鱼的稀有度，使用固定的概率分布
            rarity_probs = {
                1: 0.40,  # 普通 40%
                2: 0.305,  # 稀有 30.5%
                3: 0.205,  # 史诗 20.5%
                4: 0.08,  # 传说 8%
                5: 0.01   # 神话 1%
            }
            
            # 应用稀有度加成，提高更高稀有度的概率
            if rare_chance > 0:
                # 将一部分概率从低稀有度转移到高稀有度
                transfer_prob = rare_chance * 0.5  # 最多转移50%的概率
                
                rarity_probs[1] -= transfer_prob * 0.4  # 减少40%的转移概率
                rarity_probs[2] -= transfer_prob * 0.3  # 减少30%的转移概率
                rarity_probs[3] -= transfer_prob * 0.2  # 减少20%的转移概率
                
                # 增加更高稀有度的概率
                rarity_probs[4] += transfer_prob * 0.7  # 增加70%的转移概率
                rarity_probs[5] += transfer_prob * 0.3  # 增加30%的转移概率
                
                # 确保概率都是正数
                for r in rarity_probs:
                    rarity_probs[r] = max(0.001, rarity_probs[r])
            
            # 基于概率分布选择稀有度
            rarity_roll = random.random()
            cumulative_prob = 0
            selected_rarity = 1  # 默认为1
            
            for rarity, prob in sorted(rarity_probs.items()):
                cumulative_prob += prob
                if rarity_roll <= cumulative_prob:
                    selected_rarity = rarity
                    break
            
            # 根据稀有度获取一条鱼
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                
                # 获取指定稀有度的所有鱼
                cursor.execute("""
                    SELECT fish_id, name, rarity, base_value, min_weight, max_weight
                    FROM fish
                    WHERE rarity = ?
                """, (selected_rarity,))
                
                fishes = cursor.fetchall()
                if not fishes:
                    # 如果没有对应稀有度的鱼，回退到随机选择
                    cursor.execute("""
                        SELECT fish_id, name, rarity, base_value, min_weight, max_weight
                        FROM fish
                        ORDER BY RANDOM()
                        LIMIT 1
                    """)
                    fish = dict(cursor.fetchone())
                else:
                    # 在同稀有度内，基于价值反比来选择鱼（价值越高，概率越低）
                    # 计算所有鱼的总价值倒数
                    total_inverse_value = sum(1.0 / (f['base_value'] or 1) for f in fishes)
                    
                    # 为每条鱼分配概率
                    fish_probs = []
                    for f in fishes:
                        # 避免除以零
                        inv_value = 1.0 / (f['base_value'] or 1)
                        prob = inv_value / total_inverse_value
                        fish_probs.append((dict(f), prob))
                    
                    # 基于概率选择鱼
                    fish_roll = random.random()
                    cum_prob = 0
                    fish = fish_probs[0][0]  # 默认选第一条
                    
                    for f, prob in fish_probs:
                        cum_prob += prob
                        if fish_roll <= cum_prob:
                            fish = f
                            break
            
            # 考虑减少垃圾鱼的概率（如果选中了垃圾鱼且有垃圾减免）
            is_garbage = fish['rarity'] == 1 and fish['base_value'] <= 2  # 简单判断是否为垃圾
            if is_garbage and garbage_reduction > 0 and random.random() < garbage_reduction:
                # 重新随机一条非垃圾鱼
                with self.db._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT fish_id, name, rarity, base_value, min_weight, max_weight
                        FROM fish
                        WHERE NOT (rarity = 1 AND base_value <= 2)
                        ORDER BY RANDOM()
                        LIMIT 1
                    """)
                    non_garbage = cursor.fetchone()
                    if non_garbage:
                        fish = dict(non_garbage)
            
            # 计算鱼的重量和价值
            weight = random.randint(fish['min_weight'], fish['max_weight']) 
            
            # 应用价值修饰符（包括饰品的金币加成）
            value = int(fish['base_value'] * quality_modifier)
            
            # 应用金币加成（如果有装备饰品）
            if equipped_accessory:
                acc_coin_bonus = equipped_accessory.get('bonus_coin_modifier', 1.0)
                value = int(value * acc_coin_bonus)
            
            # 更新用户库存和统计
            self.db.add_fish_to_inventory(user_id, fish['fish_id'])
            self.db.update_user_fishing_stats(user_id, weight, value)
            
            # 添加钓鱼记录
            self.db.add_fishing_record(
                user_id=user_id,
                fish_id=fish['fish_id'],
                weight=weight,
                value=value,
                bait_id=current_bait.get('bait_id') if current_bait else (consumed_bait.get('bait_id') if consumed_bait else None)
            )
            
            # 构建结果，包含鱼饵效果信息
            result = {
                "success": True,
                "fish": {
                    "name": fish['name'],
                    "rarity": fish['rarity'],
                    "weight": weight,
                    "value": value
                }
            }
            
            if bait_effect:
                result["bait_effect"] = bait_effect
                
            # 添加装备效果信息
            equipment_effects = []
            if quality_modifier > 1.0:
                equipment_effects.append(f"鱼价值增加{int((quality_modifier-1)*100)}%")
            if quantity_modifier > 1.0:
                equipment_effects.append(f"渔获数量增加{int((quantity_modifier-1)*100)}%")
            if rare_chance > 0.0:
                equipment_effects.append(f"稀有度提升{int(rare_chance*100)}%")
            if garbage_reduction > 0.0:
                equipment_effects.append(f"垃圾减少{int(garbage_reduction*100)}%")
                
            if equipment_effects:
                result["equipment_effects"] = equipment_effects
            
            return result
        else:
            # 钓鱼失败时，单独更新最后钓鱼时间
            self.db.set_user_last_fishing_time(user_id)
            failure_msg = "💨 什么都没钓到..."
            if bait_effect:
                failure_msg += f"（鱼饵效果：{bait_effect}）"
            return {"success": False, "message": failure_msg}

    def toggle_auto_fishing(self, user_id: str) -> Dict:
        """开启/关闭自动钓鱼"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        success = self.db.toggle_user_auto_fishing(user_id)
        if success:
            current_status = self.db.get_user_auto_fishing_status(user_id)
            status_text = "开启" if current_status else "关闭"
            return {"success": True, "message": f"自动钓鱼已{status_text}", "status": current_status}
        else:
            return {"success": False, "message": "操作失败，请稍后再试"}

    def sell_all_fish(self, user_id: str) -> Dict:
        """卖出所有鱼"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 获取总价值
        total_value = self.db.get_user_fish_inventory_value(user_id)
        if total_value <= 0:
            return {"success": False, "message": "你没有可以卖出的鱼"}
            
        # 清空库存并更新金币
        self.db.clear_user_fish_inventory(user_id)
        self.db.update_user_coins(user_id, total_value)
        
        return {"success": True, "message": f"已卖出所有鱼，获得 {total_value} 金币"}

    def sell_fish_by_rarity(self, user_id: str, rarity: int) -> Dict:
        """卖出指定稀有度的鱼"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 验证稀有度参数
        if not (1 <= rarity <= 5):
            return {"success": False, "message": "无效的稀有度，应为1-5之间的整数"}
            
        # 获取指定稀有度鱼的总价值
        total_value = self.db.get_user_fish_inventory_value_by_rarity(user_id, rarity)
        if total_value <= 0:
            return {"success": False, "message": f"你没有稀有度为 {rarity} 的鱼可以卖出"}
            
        # 清空指定稀有度的鱼并更新金币
        self.db.clear_user_fish_by_rarity(user_id, rarity)
        self.db.update_user_coins(user_id, total_value)
        
        return {"success": True, "message": f"已卖出稀有度为 {rarity} 的鱼，获得 {total_value} 金币"}

    def get_all_titles(self) -> Dict:
        """查看所有称号"""
        titles = self.db.get_all_titles()
        return {"success": True, "titles": titles}

    def get_all_achievements(self) -> Dict:
        """查看所有成就"""
        achievements = self.db.get_all_achievements()
        return {"success": True, "achievements": achievements}

    def get_user_titles(self, user_id: str) -> Dict:
        """查看用户已有称号"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        titles = self.db.get_user_titles(user_id)
        return {"success": True, "titles": titles}

    def get_user_achievements(self, user_id: str) -> Dict:
        """查看用户已有成就"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 获取所有成就
        all_achievements = self.db.get_all_achievements()
        
        # 获取用户成就进度
        progress_records = self.db.get_user_achievement_progress(user_id)
        progress_map = {record['achievement_id']: record for record in progress_records}
        
        # 获取用户统计数据
        stats = self.db.get_user_fishing_stats(user_id)
        
        # 处理每个成就
        achievements = []
        for achievement in all_achievements:
            achievement_id = achievement['achievement_id']
            progress_record = progress_map.get(achievement_id, {
                'current_progress': 0,
                'completed_at': None,
                'claimed_at': None
            })
            
            # 计算当前进度
            current_progress = progress_record['current_progress']
            if current_progress == 0:  # 如果进度为0，重新计算
                if achievement['target_type'] == 'total_fish_count':
                    current_progress = stats.get('total_count', 0)
                elif achievement['target_type'] == 'total_coins_earned':
                    current_progress = stats.get('total_value', 0)
                elif achievement['target_type'] == 'total_weight_caught':
                    current_progress = stats.get('total_weight', 0)
                elif achievement['target_type'] == 'specific_fish_count':
                    if achievement['target_fish_id'] is None:
                        current_progress = self.db.get_user_unique_fish_count(user_id)
                    else:
                        current_progress = self.db.get_user_specific_fish_count(user_id, achievement['target_fish_id'])
                
                # 更新进度
                self.db.update_user_achievement_progress(
                    user_id, 
                    achievement_id, 
                    current_progress,
                    current_progress >= achievement['target_value']
                )
            
            achievements.append({
                **achievement,
                'is_completed': progress_record['completed_at'] is not None,
                'is_claimed': progress_record['claimed_at'] is not None,
                'progress': current_progress,
                'target_value': achievement['target_value']
            })
        
        return {"success": True, "achievements": achievements}

    def get_all_baits(self) -> Dict:
        """查看所有鱼饵"""
        baits = self.db.get_all_baits()
        return {"success": True, "baits": baits}

    def get_user_baits(self, user_id: str) -> Dict:
        """查看用户已有鱼饵"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        baits = self.db.get_user_baits(user_id)
        return {"success": True, "baits": baits}

    def buy_bait(self, user_id: str, bait_id: int, quantity: int = 1) -> Dict:
        """购买鱼饵"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 获取鱼饵信息
        bait = self.db.get_bait_info(bait_id)
        if not bait:
            return {"success": False, "message": "鱼饵不存在"}
            
        # 检查用户金币是否足够
        user_coins = self.db.get_user_coins(user_id)
        total_cost = bait['cost'] * quantity
        if user_coins < total_cost:
            return {"success": False, "message": f"金币不足，需要 {total_cost} 金币"}
            
        # 扣除金币并添加鱼饵
        self.db.update_user_coins(user_id, -total_cost)
        self.db.add_bait_to_inventory(user_id, bait_id, quantity)
        
        return {"success": True, "message": f"成功购买 {bait['name']} x{quantity}"}

    def get_all_rods(self) -> Dict:
        """查看所有鱼竿"""
        rods = self.db.get_all_rods()
        return {"success": True, "rods": rods}

    def get_user_rods(self, user_id: str) -> Dict:
        """查看用户已有鱼竿"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        rods = self.db.get_user_rods(user_id)
        return {"success": True, "rods": rods}

    def buy_rod(self, user_id: str, rod_id: int) -> Dict:
        """购买鱼竿"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 获取鱼竿信息
        rod = self.db.get_rod_info(rod_id)
        if not rod:
            return {"success": False, "message": "鱼竿不存在"}
            
        # 检查鱼竿是否可购买
        if rod['source'] != 'shop' or rod['purchase_cost'] is None:
            return {"success": False, "message": "此鱼竿无法直接购买"}
            
        # 检查用户金币是否足够
        user_coins = self.db.get_user_coins(user_id)
        if user_coins < rod['purchase_cost']:
            return {"success": False, "message": f"金币不足，需要 {rod['purchase_cost']} 金币"}
            
        # 扣除金币并添加鱼竿
        self.db.update_user_coins(user_id, -rod['purchase_cost'])
        self.db.add_rod_to_inventory(user_id, rod_id, rod['durability'])
        
        return {"success": True, "message": f"成功购买 {rod['name']}"}

    def get_all_accessories(self) -> Dict:
        """查看所有饰品"""
        accessories = self.db.get_all_accessories()
        return {"success": True, "accessories": accessories}

    def get_user_accessories(self, user_id: str) -> Dict:
        """查看用户已有饰品"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        accessories = self.db.get_user_accessories(user_id)
        return {"success": True, "accessories": accessories}

    def use_bait(self, user_id: str, bait_id: int) -> Dict:
        """使用鱼饵"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error

        # 获取鱼饵信息
        bait_info = self.db.get_bait_info(bait_id)
        if not bait_info:
            return {"success": False, "message": "鱼饵不存在"}
        
        # 检查用户是否已有正在使用的鱼饵
        current_bait = self.db.get_user_current_bait(user_id)
        if current_bait:
            remaining_text = ""
            if current_bait.get('duration_minutes', 0) > 0:
                remaining_text = f"，剩余时间：{int(current_bait.get('remaining_minutes', 0))}分钟"
            return {"success": False, "message": f"你已经在使用【{current_bait['name']}】{remaining_text}，请等待当前鱼饵效果结束或使用完毕"}
        
        # 设置用户当前鱼饵
        success = self.db.set_user_current_bait(user_id, bait_id)
        if not success:
            return {"success": False, "message": f"你没有【{bait_info['name']}】，请先购买"}
        
        # 构建响应消息
        duration_text = ""
        if bait_info.get('duration_minutes', 0) > 0:
            duration_text = f"，持续时间：{bait_info['duration_minutes']}分钟"
            
        return {
            "success": True, 
            "message": f"成功使用【{bait_info['name']}】{duration_text}，效果：{bait_info['effect_description']}",
            "bait": bait_info
        }

    def get_current_bait(self, user_id: str) -> Dict:
        """获取用户当前使用的鱼饵"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        bait_info = self.db.get_user_current_bait(user_id)
        if not bait_info:
            return {"success": False, "message": "你当前没有使用任何鱼饵"}
            
        remaining_text = ""
        if bait_info.get('duration_minutes', 0) > 0:
            remaining_text = f"，剩余时间：{int(bait_info.get('remaining_minutes', 0))}分钟"
            
        return {
            "success": True,
            "message": f"当前使用的鱼饵：【{bait_info['name']}】{remaining_text}，效果：{bait_info['effect_description']}",
            "bait": bait_info
        }

    def get_all_gacha_pools(self) -> Dict:
        """获取所有抽奖奖池信息"""
        pools = self.db.get_all_gacha_pools()
        return {
            "success": True,
            "pools": pools
        }
        
    def get_gacha_pool_details(self, pool_id: int) -> Dict:
        """获取特定奖池的详细信息"""
        pool_details = self.db.get_gacha_pool_details(pool_id)
        if not pool_details:
            return {"success": False, "message": "奖池不存在"}
            
        return {
            "success": True,
            "pool_details": pool_details
        }
        
    def multi_gacha(self, user_id: str, pool_id: int, count: int = 10) -> Dict:
        """执行十连抽卡"""
        # 获取抽卡池信息
        pool_info = self.db.get_gacha_pool_info(pool_id)
        if not pool_info:
            return {"success": False, "message": "抽卡池不存在"}

        # 检查用户金币是否足够
        cost = pool_info.get('cost_coins', 0) * count
        user_coins = self.db.get_user_coins(user_id)
        if user_coins < cost:
            return {"success": False, "message": f"金币不足，需要 {cost} 金币"}

        # 扣除金币
        if not self.db.update_user_coins(user_id, -cost):
            return {"success": False, "message": "扣除金币失败"}

        # 执行多次抽卡
        results = []
        rewards_by_rarity = {}

        for _ in range(count):
            result = self._perform_single_gacha(user_id, pool_id)
            if not result.get("success"):
                # 如果抽卡失败，退还金币
                self.db.update_user_coins(user_id, cost)
                return result

            item = result.get("item", {})
            results.append(item)

            # 按稀有度分组
            rarity = item.get("rarity", 1)
            if rarity not in rewards_by_rarity:
                rewards_by_rarity[rarity] = []
            rewards_by_rarity[rarity].append(item)

        return {
            "success": True,
            "results": results,
            "rewards_by_rarity": rewards_by_rarity
        }
    
    def _perform_single_gacha(self, user_id: str, pool_id: int) -> Dict:
        """执行单次抽卡"""
        # 获取抽卡池信息
        pool_info = self.db.get_gacha_pool_info(pool_id)
        if not pool_info:
            return {"success": False, "message": "抽卡池不存在"}

        # 检查用户金币是否足够
        cost = pool_info.get('cost_coins', 0)
        user_coins = self.db.get_user_coins(user_id)
        if user_coins < cost:
            return {"success": False, "message": f"金币不足，需要 {cost} 金币"}

        # 扣除金币
        if not self.db.update_user_coins(user_id, -cost):
            return {"success": False, "message": "扣除金币失败"}

        # 获取抽卡池物品列表
        items = self.db.get_gacha_pool_items(pool_id)
        if not items:
            return {"success": False, "message": "抽卡池为空"}

        # 计算总权重
        total_weight = sum(item['weight'] for item in items)
        if total_weight <= 0:
            return {"success": False, "message": "抽卡池配置错误"}

        # 随机抽取物品
        rand = random.uniform(0, total_weight)
        current_weight = 0
        selected_item = None

        for item in items:
            current_weight += item['weight']
            if rand <= current_weight:
                selected_item = item
                break

        if not selected_item:
            return {"success": False, "message": "抽卡失败"}

        # 根据物品类型处理奖励
        item_type = selected_item['item_type']
        item_id = selected_item['item_id']
        quantity = selected_item.get('quantity', 1)

        # 获取物品详细信息
        item_info = None
        if item_type == 'rod':
            item_info = self.db.get_rod_info(item_id)
        elif item_type == 'accessory':
            item_info = self.db.get_accessory_info(item_id)
        elif item_type == 'bait':
            item_info = self.db.get_bait_info(item_id)

        if not item_info:
            return {"success": False, "message": "获取物品信息失败"}

        # 发放奖励
        success = False
        if item_type == 'rod':
            success = self.db.add_rod_to_inventory(user_id, item_id)
        elif item_type == 'accessory':
            success = self.db.add_accessory_to_inventory(user_id, item_id)
        elif item_type == 'bait':
            success = self.db.add_bait_to_inventory(user_id, item_id, quantity)
        elif item_type == 'coins':
            success = self.db.update_user_coins(user_id, item_id * quantity)
        elif item_type == 'premium_currency':
            success = self.db.update_user_currency(user_id, 0, item_id * quantity)

        if not success:
            # 如果发放失败，退还金币
            self.db.update_user_coins(user_id, cost)
            return {"success": False, "message": "发放奖励失败"}

        # 记录抽卡结果
        self.db.record_gacha_result(
            user_id=user_id,
            gacha_pool_id=pool_id,
            item_type=item_type,
            item_id=item_id,
            item_name=item_info.get('name', '未知物品'),
            quantity=quantity,
            rarity=item_info.get('rarity', 1)
        )

        return {
            "success": True,
            "item": {
                "type": item_type,
                "id": item_id,
                "name": item_info.get('name', '未知物品'),
                "quantity": quantity,
                "rarity": item_info.get('rarity', 1)
            }
        }
    
    def gacha(self, user_id: str, pool_id: int) -> Dict:
        """进行一次抽奖"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 获取抽奖池信息
        pool = self.db.get_gacha_pool_info(pool_id)
        if not pool:
            return {"success": False, "message": "抽奖池不存在"}
            
        # 检查用户货币是否足够
        user_currency = self.db.get_user_currency(user_id)
        if user_currency['coins'] < pool['cost_coins'] or user_currency['premium_currency'] < pool['cost_premium_currency']:
            return {"success": False, "message": "货币不足，无法抽奖"}
            
        # 扣除货币
        self.db.update_user_currency(user_id, -pool['cost_coins'], -pool['cost_premium_currency'])
        
        # 执行抽奖
        result = self._perform_single_gacha(user_id, pool_id)
        if not result:
            return {"success": False, "message": "抽奖失败，请稍后再试"}
            
        # 将物品信息添加到rewards_by_rarity中，便于前端显示
        rewards_by_rarity = {}
        rarity = result.get('rarity', 1)
        rewards_by_rarity[rarity] = [result]
            
        return {
            "success": True,
            "message": f"恭喜获得: {result['name']}",
            "item": result,
            "rewards_by_rarity": rewards_by_rarity
        }

    # --- 自动钓鱼相关方法 ---
    def get_fishing_cost(self) -> int:
        """获取钓鱼成本"""
        # 实际项目中可能会根据不同因素计算钓鱼成本，这里简化为固定值
        return 10

    def start_auto_fishing_task(self):
        """启动自动钓鱼任务"""
        if self.auto_fishing_thread and self.auto_fishing_thread.is_alive():
            self.LOG.info("自动钓鱼线程已在运行中")
            return
            
        self.auto_fishing_running = True
        self.auto_fishing_thread = threading.Thread(target=self._auto_fishing_loop, daemon=True)
        self.auto_fishing_thread.start()
        self.LOG.info("自动钓鱼线程已启动")
        
    def stop_auto_fishing_task(self):
        """停止自动钓鱼任务"""
        self.auto_fishing_running = False
        if self.auto_fishing_thread:
            self.auto_fishing_thread.join(timeout=1.0)
            self.LOG.info("自动钓鱼线程已停止")

    def _auto_fishing_loop(self):
        """自动钓鱼循环任务"""
        while self.auto_fishing_running:
            try:
                # 获取所有开启自动钓鱼的用户
                auto_fishing_users = self.db.get_auto_fishing_users()
                
                if auto_fishing_users:
                    self.LOG.info(f"执行自动钓鱼任务，{len(auto_fishing_users)}个用户")
                    
                    for user_id in auto_fishing_users:
                        try:
                            # 检查CD时间
                            current_time = time.time()
                            last_time = self.db.get_last_fishing_time(user_id)
                            
                            if current_time - last_time < 300:  # 5分钟CD
                                self.LOG.debug(f"用户 {user_id} 钓鱼CD中，跳过")
                                continue
                                
                            # 检查金币是否足够
                            user_coins = self.db.get_user_coins(user_id)
                            if user_coins < self.get_fishing_cost():
                                # 金币不足，关闭自动钓鱼
                                self.db.set_auto_fishing_status(user_id, False)
                                self.LOG.info(f"用户 {user_id} 金币不足，已关闭自动钓鱼")
                                continue
                            
                            # 执行钓鱼
                            result = self.fish(user_id, is_auto=True)
                            
                            # 记录日志
                            if result["success"]:
                                fish = result["fish"]
                                log_message = f"用户 {user_id} 自动钓鱼成功: {fish['name']}，稀有度: {fish['rarity']}，价值: {fish['value']}"
                            else:
                                log_message = f"用户 {user_id} 自动钓鱼失败: {result['message']}"
                                
                            self.LOG.info(log_message)
                            
                        except Exception as e:
                            self.LOG.error(f"用户 {user_id} 自动钓鱼出错: {e}")
                
                # 每分钟检查一次
                time.sleep(60)
                
            except Exception as e:
                self.LOG.error(f"自动钓鱼任务出错: {e}", exc_info=True)
                time.sleep(60)  # 出错后等待1分钟再重试
                
    def set_user_auto_fishing(self, user_id: str, status: bool) -> Dict:
        """设置用户自动钓鱼状态"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 如果启用自动钓鱼，检查用户钱是否够钓鱼成本
        if status:
            user_coins = self.db.get_user_coins(user_id)
            if user_coins < self.get_fishing_cost():
                return {"success": False, "message": "金币不足，无法开启自动钓鱼"}
        
        success = self.db.set_auto_fishing_status(user_id, status)
        if success:
            status_text = "开启" if status else "关闭"
            return {"success": True, "message": f"已{status_text}自动钓鱼"}
        else:
            return {"success": False, "message": "设置自动钓鱼状态失败，请稍后再试"}

    def is_auto_fishing_enabled(self, user_id: str) -> bool:
        """检查用户是否开启了自动钓鱼"""
        error = self._check_registered_or_return(user_id)
        if error:
            return False
            
        # 直接使用之前实现的获取自动钓鱼状态方法
        return self.db.get_user_auto_fishing_status(user_id)

    def get_fish_pond(self, user_id: str) -> Dict:
        """查看用户的鱼塘（所有钓到的鱼）"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 获取用户的鱼类库存
        fish_inventory = self.db.get_user_fish_inventory(user_id)
        
        # 获取鱼塘统计信息
        stats = self.db.get_user_fish_stats(user_id)
        
        if not fish_inventory:
            return {
                "success": True, 
                "message": "你的鱼塘里还没有鱼，快去钓鱼吧！",
                "stats": stats,
                "fishes": []
            }
        
        # 按稀有度分组整理鱼类
        fish_by_rarity = {}
        for fish in fish_inventory:
            rarity = fish['rarity']
            if rarity not in fish_by_rarity:
                fish_by_rarity[rarity] = []
            fish_by_rarity[rarity].append(fish)
        
        return {
            "success": True,
            "message": f"你的鱼塘里有 {stats.get('total_count', 0)} 条鱼，总价值: {stats.get('total_value', 0)} 金币",
            "stats": stats,
            "fish_by_rarity": fish_by_rarity,
            "fishes": fish_inventory
        }

    def daily_sign_in(self, user_id: str) -> Dict:
        """用户每日签到，随机获得100-300金币"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 检查用户今天是否已经签到
        if self.db.check_daily_sign_in(user_id):
            return {"success": False, "message": "你今天已经签到过了，明天再来吧！"}
        
        # 检查是否需要重置连续登录天数（昨天没有签到）
        self.db.reset_login_streak(user_id)
        
        # 随机生成今天的签到奖励金币（100-300之间）
        coins_reward = random.randint(100, 300)
        
        # 记录签到并发放奖励
        if self.db.record_daily_sign_in(user_id, coins_reward):
            # 获取当前连续签到天数
            consecutive_days = self.db.get_consecutive_login_days(user_id)
            
            # 构建返回消息
            result = {
                "success": True,
                "message": f"签到成功！获得 {coins_reward} 金币",
                "coins_reward": coins_reward,
                "consecutive_days": consecutive_days
            }
            
            # 如果连续签到达到特定天数，给予额外奖励
            if consecutive_days in [7, 14, 30, 60, 90, 180, 365]:
                bonus_coins = consecutive_days * 10  # 简单计算额外奖励
                self.db.update_user_coins(user_id, bonus_coins)
                result["bonus_coins"] = bonus_coins
                result["message"] += f"，连续签到 {consecutive_days} 天，额外奖励 {bonus_coins} 金币！"
                
            return result
        else:
            return {"success": False, "message": "签到失败，请稍后再试"}

    def equip_accessory(self, user_id: str, accessory_instance_id: int) -> Dict:
        """装备指定的饰品"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 检查饰品是否存在并属于用户
        if self.db.equip_accessory(user_id, accessory_instance_id):
            # 获取饰品信息
            accessory = self.db.get_user_equipped_accessory(user_id)
            if accessory:
                return {
                    "success": True,
                    "message": f"成功装备【{accessory['name']}】！",
                    "accessory": accessory
                }
            else:
                return {
                    "success": True,
                    "message": "饰品已装备，但无法获取详细信息"
                }
        else:
            return {
                "success": False,
                "message": "装备饰品失败，请确认该饰品属于你"
            }
            
    def unequip_accessory(self, user_id: str) -> Dict:
        """取消装备当前饰品"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        if self.db.unequip_accessory(user_id):
            return {
                "success": True,
                "message": "已取消装备当前饰品"
            }
        else:
            return {
                "success": False,
                "message": "取消装备饰品失败"
            }
            
    def get_user_equipped_accessory(self, user_id: str) -> Dict:
        """获取用户当前装备的饰品"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        accessory = self.db.get_user_equipped_accessory(user_id)
        if not accessory:
            return {"success": True, "accessory": None}
            
        return {"success": True, "accessory": accessory}

    def get_user_currency(self, user_id: str) -> Dict:
        """获取用户的货币信息"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 获取用户的金币和钻石数量
        coins = self.db.get_user_coins(user_id)
        # premium_currency = self.db.get_user_premium_currency(user_id)
        
        return {
            "success": True,
            "coins": coins,
            "premium_currency": 0
        }

    def adjust_gacha_pool_weights(self) -> Dict:
        """调整奖池物品权重，使稀有物品更难抽出"""
        success = self.db.adjust_gacha_pool_weights()
        if success:
            return {
                "success": True,
                "message": "奖池权重调整成功，稀有物品现在更难抽出"
            }
        else:
            return {
                "success": False,
                "message": "奖池权重调整失败，请检查日志"
            }

    def check_wipe_bomb_available(self, user_id: str) -> bool:
        """检查用户今天是否已经进行过擦弹"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            today = date.today().isoformat()
            cursor.execute("""
                SELECT 1 FROM wipe_bomb_log
                WHERE user_id = ? AND DATE(timestamp) = ?
            """, (user_id, today))
            return cursor.fetchone() is None  # 如果为None，表示今天还没有进行过擦弹

    def perform_wipe_bomb(self, user_id: str, contribution_amount: int) -> Dict:
        """执行擦弹操作，向公共奖池投入金币并获得随机倍数的奖励"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        # 检查是否已经进行过擦弹
        if not self.check_wipe_bomb_available(user_id):
            return {"success": False, "message": "你今天已经进行过擦弹，明天再来吧！"}
            
        # 验证投入金额
        if contribution_amount <= 0:
            return {"success": False, "message": "投入金额必须大于0"}
            
        # 检查用户金币是否足够
        user_coins = self.db.get_user_coins(user_id)
        if user_coins < contribution_amount:
            return {"success": False, "message": f"金币不足，当前拥有 {user_coins} 金币"}
            
        # 扣除用户金币
        self.db.update_user_coins(user_id, -contribution_amount)
        
        # 使用加权随机算法生成奖励倍数（0-10倍，保留1位小数）
        # 定义倍数区间和对应的权重
        ranges = [
            (0.0, 0.5, 35),    # 0.0-0.5倍，权重35
            (0.5, 1.0, 25),    # 0.5-1.0倍，权重25
            (1.0, 2.0, 20),    # 1.0-2.0倍，权重20
            (2.0, 3.0, 10),    # 2.0-3.0倍，权重10
            (3.0, 5.0, 7),     # 3.0-5.0倍，权重7
            (5.0, 8.0, 2),     # 5.0-8.0倍，权重2
            (8.0, 10.0, 1),    # 8.0-10.0倍，权重1
        ]
        
        # 计算总权重
        total_weight = sum(weight for _, _, weight in ranges)
        
        # 随机选择一个区间
        random_value = random.random() * total_weight
        current_weight = 0
        selected_range = ranges[0]  # 默认第一个区间
        
        for range_min, range_max, weight in ranges:
            current_weight += weight
            if random_value <= current_weight:
                selected_range = (range_min, range_max, weight)
                break
                
        # 在选中的区间内随机生成倍数值
        range_min, range_max, _ = selected_range
        reward_multiplier = round(random.uniform(range_min, range_max), 1)
        
        # 计算实际奖励金额
        reward_amount = int(contribution_amount * reward_multiplier)
        
        # 将奖励金额添加到用户账户
        self.db.update_user_coins(user_id, reward_amount)
        
        # 记录擦弹操作
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO wipe_bomb_log 
                (user_id, contribution_amount, reward_multiplier, reward_amount)
                VALUES (?, ?, ?, ?)
            """, (user_id, contribution_amount, reward_multiplier, reward_amount))
            conn.commit()
        
        # 构建返回消息
        profit = reward_amount - contribution_amount
        profit_text = f"盈利 {profit}" if profit > 0 else f"亏损 {-profit}"
        
        return {
            "success": True,
            "message": f"擦弹结果：投入 {contribution_amount} 金币，获得 {reward_multiplier}倍 奖励，共 {reward_amount} 金币，{profit_text}！",
            "contribution": contribution_amount,
            "multiplier": reward_multiplier,
            "reward": reward_amount,
            "profit": profit
        }
        
    def get_wipe_bomb_history(self, user_id: str, limit: int = 10) -> Dict:
        """获取用户的擦弹历史记录"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT contribution_amount, reward_multiplier, reward_amount, timestamp
                FROM wipe_bomb_log
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, limit))
            
            records = []
            for row in cursor.fetchall():
                record = dict(row)
                # 计算盈利
                record['profit'] = record['reward_amount'] - record['contribution_amount']
                records.append(record)
                
            return {
                "success": True,
                "records": records,
                "available_today": self.check_wipe_bomb_available(user_id)
            }

    def get_user_equipment(self, user_id: str) -> Dict:
        """获取用户当前装备的鱼竿和饰品信息，包括各种加成属性"""
        error = self._check_registered_or_return(user_id)
        if error:
            return {"success": False, "message": error["message"], "equipment": {}}
            
        equipment = self.db.get_user_equipment(user_id)
        
        # 获取鱼竿详细信息
        user_rods = self.db.get_user_rods(user_id)
        equipped_rod = next((rod for rod in user_rods if rod.get('is_equipped')), None)
        
        # 获取饰品详细信息
        equipped_accessory = self.db.get_user_equipped_accessory(user_id)
        
        return {
            "success": True,
            "equipment": equipment,
            "rod": equipped_rod,
            "accessory": equipped_accessory
        }

    def equip_rod(self, user_id: str, rod_instance_id: int) -> Dict:
        """装备指定的鱼竿"""
        error = self._check_registered_or_return(user_id)
        if error:
            return error
        
        if self.db.equip_rod(user_id, rod_instance_id):
            return {"success": True, "message": "鱼竿装备成功"}
        else:
            return {"success": False, "message": "鱼竿装备失败，请确认鱼竿ID是否正确"}
            
    def get_user_fishing_records(self, user_id: str, limit: int = 10) -> Dict:
        """获取用户的钓鱼记录
        
        Args:
            user_id: 用户ID
            limit: 最多返回的记录数
            
        Returns:
            包含钓鱼记录的字典
        """
        error = self._check_registered_or_return(user_id)
        if error:
            return error
            
        records = self.db.get_user_fishing_records(user_id, limit)
        return {
            "success": True,
            "records": records,
            "count": len(records)
        }

    def start_achievement_check_task(self):
        """启动成就检查任务"""
        if self.achievement_check_thread and self.achievement_check_thread.is_alive():
            self.LOG.info("成就检查线程已在运行中")
            return
            
        self.achievement_check_running = True
        self.achievement_check_thread = threading.Thread(target=self._achievement_check_loop, daemon=True)
        self.achievement_check_thread.start()
        self.LOG.info("成就检查线程已启动")
        
    def stop_achievement_check_task(self):
        """停止成就检查任务"""
        self.achievement_check_running = False
        if self.achievement_check_thread:
            self.achievement_check_thread.join(timeout=1.0)
            self.LOG.info("成就检查线程已停止")

    def _achievement_check_loop(self):
        """成就检查循环任务"""
        while self.achievement_check_running:
            try:
                # 获取所有注册用户
                users = self.db.get_all_users()
                
                if users:
                    self.LOG.info(f"执行成就检查任务，{len(users)}个用户")
                    
                    for user_id in users:
                        try:
                            self._check_user_achievements(user_id)
                        except Exception as e:
                            self.LOG.error(f"用户 {user_id} 成就检查出错: {e}")
                
                # 每10分钟检查一次
                time.sleep(600)
                
            except Exception as e:
                self.LOG.error(f"成就检查任务出错: {e}", exc_info=True)
                time.sleep(60)  # 出错后等待1分钟再重试

    def _check_user_achievements(self, user_id: str):
        """检查单个用户的成就完成情况"""
        # 获取所有成就
        achievements = self.db.get_all_achievements()
        
        for achievement in achievements:
            try:
                # 检查成就是否完成
                is_completed = self._check_achievement_completion(user_id, achievement)
                
                if is_completed:
                    # 发放奖励
                    self._grant_achievement_reward(user_id, achievement)
                    
                    # 记录成就完成
                    self.db.update_user_achievement_progress(
                        user_id,
                        achievement['achievement_id'],
                        achievement['target_value'],
                        True
                    )
                    
                    # 记录日志
                    self.LOG.info(f"用户 {user_id} 完成成就: {achievement['name']}")
                    
            except Exception as e:
                self.LOG.error(f"检查成就 {achievement['name']} 时出错: {e}")

    def _check_achievement_completion(self, user_id: str, achievement: Dict) -> bool:
        """检查特定成就是否完成"""
        target_type = achievement['target_type']
        target_value = achievement['target_value']
        target_fish_id = achievement['target_fish_id']
        
        # 获取用户统计数据
        stats = self.db.get_user_fishing_stats(user_id)
        
        # 获取当前进度
        progress_records = self.db.get_user_achievement_progress(user_id)
        progress_record = next(
            (record for record in progress_records if record['achievement_id'] == achievement['achievement_id']),
            {'current_progress': 0}
        )
        current_progress = progress_record['current_progress']
        
        # 如果已经完成，直接返回
        if progress_record.get('completed_at') is not None:
            return False
        
        # 根据不同的目标类型检查完成情况
        if target_type == 'total_fish_count':
            return stats.get('total_count', 0) >= target_value
            
        elif target_type == 'specific_fish_count':
            if target_fish_id is None:
                # 检查不同种类鱼的数量
                unique_fish_count = self.db.get_user_unique_fish_count(user_id)
                return unique_fish_count >= target_value
            elif target_fish_id == -3:
                # 检查垃圾物品数量
                garbage_count = self.db.get_user_garbage_count(user_id)
                return garbage_count >= target_value
            elif target_fish_id == -4:
                # 检查深海鱼种类数量（重量大于3000的鱼）
                with self.db._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT COUNT(DISTINCT f.fish_id) as deep_sea_count
                        FROM fishing_records fr
                        JOIN fish f ON fr.fish_id = f.fish_id
                        WHERE fr.user_id = ? AND f.max_weight > 3000
                    """, (user_id,))
                    result = cursor.fetchone()
                    deep_sea_count = result['deep_sea_count'] if result else 0
                    return deep_sea_count >= target_value
            elif target_fish_id == -5:
                # 检查是否钓到过重量超过100kg的鱼
                return self.db.has_caught_heavy_fish(user_id, 100000)  # 100kg = 100000g
            else:
                # 检查特定鱼的捕获数量
                if target_fish_id in [-1, -2]:
                    return False
                specific_fish_count = self.db.get_user_specific_fish_count(user_id, target_fish_id)
                return specific_fish_count >= target_value
                
        elif target_type == 'total_coins_earned':
            return stats.get('total_value', 0) >= target_value
            
        elif target_type == 'total_weight_caught':
            return stats.get('total_weight', 0) >= target_value
            
        elif target_type == 'wipe_bomb_profit':
            if target_value == 1:  # 第一次擦弹
                return self.db.has_performed_wipe_bomb(user_id)
            elif target_value == 10:  # 10倍奖励
                return self.db.has_wipe_bomb_multiplier(user_id, 10)
            else:  # 特定盈利金额
                return self.db.has_wipe_bomb_profit(user_id, target_value)
                
        elif target_type == 'rod_collection':
            # 检查是否有特定稀有度的鱼竿
            return self.db.has_rod_of_rarity(user_id, target_value)
            
        elif target_type == 'accessory_collection':
            # 检查是否有特定稀有度的饰品
            return self.db.has_accessory_of_rarity(user_id, target_value)
            
        return False

    def _grant_achievement_reward(self, user_id: str, achievement: Dict):
        """发放成就奖励"""
        reward_type = achievement['reward_type']
        reward_value = achievement['reward_value']
        reward_quantity = achievement['reward_quantity']
        
        if reward_type == 'coins':
            self.db.update_user_coins(user_id, reward_value * reward_quantity)
            
        elif reward_type == 'premium_currency':
            self.db.update_user_currency(user_id, 0, reward_value * reward_quantity)
            
        elif reward_type == 'title':
            self.db.grant_title_to_user(user_id, reward_value)
            
        elif reward_type == 'bait':
            self.db.add_bait_to_inventory(user_id, reward_value, reward_quantity)

    def get_user_deep_sea_fish_count(self, user_id: str) -> int:
        """获取用户钓到的深海鱼种类数量（重量大于3000的鱼）"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(DISTINCT f.fish_id) as deep_sea_count
                FROM fishing_records fr
                JOIN fish f ON fr.fish_id = f.fish_id
                WHERE fr.user_id = ? AND f.max_weight > 3000
            """, (user_id,))
            result = cursor.fetchone()
            return result['deep_sea_count'] if result else 0