import random
from typing import List, Dict
from datetime import datetime, timedelta
from .db import FishingDB
import sqlite3

class FishingLottery:
    def __init__(self, db: FishingDB):
        self.db = db
        # 鱼类数据
        self.fish_data = [
            # 河鱼（淡水鱼）
            (1, '小鲫鱼', 1, 10, 100, 500),
            (2, '草鱼', 2, 50, 500, 2000),
            (3, '鲤鱼', 2, 60, 600, 2500),
            (4, '鲈鱼', 3, 100, 800, 3000),
            (5, '黑鱼', 3, 150, 1000, 4000),
            (6, '金龙鱼', 4, 500, 2000, 8000),
            (7, '锦鲤', 5, 1000, 5000, 15000),
            (8, '泥鳅', 1, 15, 50, 200),
            (9, '小虾', 1, 20, 30, 100),
            (10, '鲢鱼', 2, 55, 500, 2000),
            (11, '鳊鱼', 2, 65, 600, 2500),
            (12, '鳜鱼', 3, 120, 1000, 5000),
            (13, '胭脂鱼', 3, 180, 1200, 6000),
            (14, '清道夫', 4, 600, 2000, 10000),
            (15, '娃娃鱼', 4, 800, 3000, 15000),
            
            # 海鱼（咸水鱼）
            (16, '沙丁鱼', 1, 12, 100, 300),
            (17, '小黄鱼', 1, 18, 150, 400),
            (18, '海虾', 1, 25, 50, 150),
            (19, '鲅鱼', 2, 70, 700, 3000),
            (20, '带鱼', 2, 75, 800, 3500),
            (21, '黄花鱼', 2, 80, 900, 4000),
            (22, '鲳鱼', 2, 85, 1000, 4500),
            (23, '鲨鱼', 3, 200, 5000, 20000),
            (24, '金枪鱼', 3, 250, 6000, 25000),
            (25, '石斑鱼', 3, 300, 7000, 30000),
            (26, '鲷鱼', 3, 350, 8000, 35000),
            (27, '蓝鳍金枪鱼', 4, 1000, 10000, 50000),
            (28, '剑鱼', 4, 1200, 12000, 60000),
            (29, '海豚', 4, 1500, 15000, 70000),
            (30, '鲸鱼', 4, 2000, 20000, 100000),
            (31, '龙王', 5, 5000, 50000, 200000),
            (32, '美人鱼', 5, 8000, 80000, 300000),
            (33, '深海巨妖', 5, 10000, 100000, 500000),
            (34, '海神三叉戟', 5, 15000, 150000, 1000000)
        ]
        
        # 奖池设置
        self.lottery_pools = {
            "钓鱼抽奖池": {
                "cost": 160,  # 每次抽奖需要160金币
                "prizes": [
                    # 稀有度1的鱼（40%概率）
                    {"type": "fish", "name": "小鲫鱼", "chance": 8, "amount": 1},
                    {"type": "fish", "name": "泥鳅", "chance": 8, "amount": 1},
                    {"type": "fish", "name": "小虾", "chance": 8, "amount": 1},
                    {"type": "fish", "name": "沙丁鱼", "chance": 8, "amount": 1},
                    {"type": "fish", "name": "小黄鱼", "chance": 8, "amount": 1},
                    
                    # 稀有度2的鱼（30%概率）
                    {"type": "fish", "name": "草鱼", "chance": 5, "amount": 1},
                    {"type": "fish", "name": "鲤鱼", "chance": 5, "amount": 1},
                    {"type": "fish", "name": "鲢鱼", "chance": 5, "amount": 1},
                    {"type": "fish", "name": "鳊鱼", "chance": 5, "amount": 1},
                    {"type": "fish", "name": "鲅鱼", "chance": 5, "amount": 1},
                    {"type": "fish", "name": "带鱼", "chance": 5, "amount": 1},
                    
                    # 稀有度3的鱼（20%概率）
                    {"type": "fish", "name": "鲈鱼", "chance": 3, "amount": 1},
                    {"type": "fish", "name": "黑鱼", "chance": 3, "amount": 1},
                    {"type": "fish", "name": "鳜鱼", "chance": 3, "amount": 1},
                    {"type": "fish", "name": "胭脂鱼", "chance": 3, "amount": 1},
                    {"type": "fish", "name": "鲨鱼", "chance": 3, "amount": 1},
                    {"type": "fish", "name": "金枪鱼", "chance": 3, "amount": 1},
                    {"type": "fish", "name": "石斑鱼", "chance": 2, "amount": 1},
                    
                    # 稀有度4的鱼（8%概率）
                    {"type": "fish", "name": "金龙鱼", "chance": 2, "amount": 1},
                    {"type": "fish", "name": "清道夫", "chance": 2, "amount": 1},
                    {"type": "fish", "name": "娃娃鱼", "chance": 2, "amount": 1},
                    {"type": "fish", "name": "蓝鳍金枪鱼", "chance": 1, "amount": 1},
                    {"type": "fish", "name": "剑鱼", "chance": 1, "amount": 1},
                    
                    # 稀有度5的鱼（2%概率）
                    {"type": "fish", "name": "锦鲤", "chance": 0.5, "amount": 1},
                    {"type": "fish", "name": "龙王", "chance": 0.5, "amount": 1},
                    {"type": "fish", "name": "美人鱼", "chance": 0.5, "amount": 1},
                    {"type": "fish", "name": "深海巨妖", "chance": 0.3, "amount": 1},
                    {"type": "fish", "name": "海神三叉戟", "chance": 0.2, "amount": 1},
                ]
            }
        }
        
        # 确保数据库中有必要的表
        self._init_db()
    
    def _init_db(self):
        """初始化抽奖相关的数据库表"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            # 创建抽奖记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS lottery_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    pool_name TEXT NOT NULL,
                    prize_type TEXT NOT NULL,
                    prize_name TEXT NOT NULL,
                    prize_amount INTEGER NOT NULL,
                    draw_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 创建每日免费抽奖次数表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_free_draws (
                    user_id TEXT PRIMARY KEY,
                    free_draws_left INTEGER DEFAULT 1,
                    last_reset_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
    
    def get_free_draws(self, user_id: str) -> int:
        """获取用户剩余的免费抽奖次数"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT free_draws_left, last_reset_time FROM daily_free_draws WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            
            if not result:
                # 新用户，插入初始数据
                cursor.execute(
                    "INSERT INTO daily_free_draws (user_id, free_draws_left) VALUES (?, 3)",
                    (user_id,)
                )
                conn.commit()
                return 3
            
            free_draws, last_reset = result
            last_reset = datetime.fromisoformat(last_reset)
            now = datetime.now()
            
            # 检查是否需要重置每日免费次数
            if (now.date() - last_reset.date()).days >= 1:
                cursor.execute(
                    "UPDATE daily_free_draws SET free_draws_left = 3, last_reset_time = ? WHERE user_id = ?",
                    (now.isoformat(), user_id)
                )
                conn.commit()
                return 3
                
            return free_draws
    
    def use_free_draw(self, user_id: str) -> bool:
        """使用一次免费抽奖机会"""
        free_draws = self.get_free_draws(user_id)
        if free_draws <= 0:
            return False
            
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE daily_free_draws SET free_draws_left = free_draws_left - 1 WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()
        return True
    
    def draw(self, user_id: str, pool_name: str, use_free: bool = False, times: int = 1) -> Dict:
        """进行一次或多次抽奖
        
        Args:
            user_id: 用户ID
            pool_name: 奖池名称
            use_free: 是否使用免费抽奖次数
            times: 抽奖次数（1或10）
            
        Returns:
            Dict: 抽奖结果
        """
        if pool_name not in self.lottery_pools:
            return {"success": False, "message": "❌ 无效的奖池名称"}
            
        pool = self.lottery_pools[pool_name]
        cost = pool["cost"] * times
        
        # 检查是否使用免费抽奖
        if use_free:
            if times > 1:
                return {"success": False, "message": "❌ 免费抽奖只能单抽"}
            if not self.use_free_draw(user_id):
                return {"success": False, "message": "❌ 今日免费抽奖次数已用完"}
        else:
            # 检查用户金币是否足够
            user_coins = self.db.get_user_coins(user_id)
            if user_coins < cost:
                return {"success": False, "message": f"❌ 金币不足！需要{cost}金币，当前拥有{user_coins}金币"}
            
            # 扣除金币
            self.db.update_user_coins(user_id, -cost)
        
        # 抽奖逻辑
        results = []
        for _ in range(times):
            prizes = pool["prizes"]
            total_chance = sum(prize["chance"] for prize in prizes)
            rand_num = random.uniform(0, total_chance)
            current_sum = 0
            
            for prize in prizes:
                current_sum += prize["chance"]
                if rand_num <= current_sum:
                    # 中奖了，记录并发放奖励
                    self._award_prize(user_id, pool_name, prize)
                    
                    # 生成中奖信息
                    message = self._generate_win_message(prize, use_free)
                    results.append(message)
                    break
        
        # 生成最终消息
        if times == 1:
            return {"success": True, "message": results[0]}
        else:
            # 十连抽特殊处理
            header = "🎉 十连抽结果：\n"
            content = "\n".join(f"{i+1}. {result}" for i, result in enumerate(results))
            return {"success": True, "message": header + content}
    
    def _award_prize(self, user_id: str, pool_name: str, prize: Dict):
        """发放奖励"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            # 记录抽奖历史
            cursor.execute(
                """
                INSERT INTO lottery_history 
                (user_id, pool_name, prize_type, prize_name, prize_amount)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, pool_name, prize["type"], 
                 prize["name"] if "name" in prize else "金币",
                 prize["amount"])
            )
            conn.commit()
            
            # 发放奖励
            if prize["type"] == "fish":
                # 获取鱼的 ID
                cursor.execute(
                    """
                    SELECT id FROM fish_config WHERE name = ?
                    """,
                    (prize["name"],)
                )
                result = cursor.fetchone()
                if result:
                    fish_id = result[0]
                    # 添加鱼到用户的鱼塘
                    self.db.add_fish_to_pond(user_id, fish_id)
    
    def _generate_win_message(self, prize: Dict, use_free: bool = False) -> str:
        """生成中奖信息"""
        prefix = ("（免费抽奖）" if use_free else "")
        if prize["type"] == "fish":
            # 获取鱼的稀有度
            rarity = next((fish[2] for fish in self.fish_data if fish[1] == prize["name"]), 1)
            rarity_stars = "⭐" * rarity
            return f"{prefix}抽中了 {prize['amount']}条 {prize['name']} {rarity_stars}！"
        return "抽奖成功！"
    
    def get_pool_info(self, pool_name: str = None) -> str:
        """获取奖池信息"""
        if pool_name and pool_name in self.lottery_pools:
            pool = self.lottery_pools[pool_name]
            info = [f"==== {pool_name} ===="]
            info.append(f"单抽费用：{pool['cost']}金币")
            info.append(f"十连费用：{pool['cost'] * 10}金币")
            info.append("\n🎣 可能获得的鱼类：")
            
            # 按稀有度分组显示
            rarity_groups = {}
            for prize in pool["prizes"]:
                if prize["type"] == "fish":
                    rarity = next((fish[2] for fish in self.fish_data if fish[1] == prize["name"]), 1)
                    if rarity not in rarity_groups:
                        rarity_groups[rarity] = []
                    rarity_groups[rarity].append(prize)
            
            # 按稀有度从高到低显示
            for rarity in sorted(rarity_groups.keys(), reverse=True):
                stars = "⭐" * rarity
                info.append(f"\n【{rarity}星】{stars}")
                for prize in rarity_groups[rarity]:
                    info.append(f"- {prize['name']} ({prize['chance']}%)")
            
            return "\n".join(info)
        
        # 显示所有奖池信息
        info = ["==== 钓鱼抽奖系统 ===="]
        info.append("🎰 可用奖池：")
        for name, pool in self.lottery_pools.items():
            info.append(f"- {name}（{pool['cost']}金币/次）")
        info.append("\n使用方法：")
        info.append("/抽奖 - 单抽一次")
        info.append("/十连抽 - 十连抽一次")
        info.append("/免费抽奖 - 使用免费次数抽奖")
        info.append("/查看奖池 - 查看奖池详情")
        info.append("\n每日可获得3次免费抽奖机会")
        return "\n".join(info) 