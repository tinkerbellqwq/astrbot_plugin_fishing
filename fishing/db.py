import threading
import sqlite3
from typing import Dict, List, Optional
import time
import os
import logging

class FishingDB:
    def __init__(self, db_path: str):
        """初始化数据库
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        
        # 确保数据目录存在
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
        
        # 初始化数据库
        self.init_db()
    
    def init_db(self) -> None:
        """初始化数据库表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 检查user_fishing表是否存在
            cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='user_fishing'
            """)
            
            if cursor.fetchone() is None:
                # 如果表不存在，创建新表
                cursor.execute('''
                    CREATE TABLE user_fishing (
                        user_id TEXT PRIMARY KEY,
                        coins INTEGER DEFAULT 100,
                        current_bait TEXT,
                        bait_start_time DATETIME,
                        total_fishing INTEGER DEFAULT 0,
                        last_steal_time INTEGER,
                        auto_fishing INTEGER DEFAULT 0,
                        last_fishing_time REAL DEFAULT 0
                    )
                ''')
                logging.info("Created new user_fishing table with correct structure")
            else:
                # 如果表存在，检查列结构
                cursor.execute("PRAGMA table_info(user_fishing)")
                columns = {info[1]: info for info in cursor.fetchall()}
                
                # 检查auto_fishing列是否存在
                if 'auto_fishing' not in columns:
                    cursor.execute('ALTER TABLE user_fishing ADD COLUMN auto_fishing INTEGER DEFAULT 0')
                    logging.info("Added auto_fishing column to user_fishing table")
                
                # 检查last_fishing_time列是否存在
                if 'last_fishing_time' not in columns:
                    cursor.execute('ALTER TABLE user_fishing ADD COLUMN last_fishing_time REAL DEFAULT 0')
                    logging.info("Added last_fishing_time column to user_fishing table")
            
            # 创建鱼类配置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS fish_config (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    rarity INTEGER,
                    base_value INTEGER,
                    min_weight INTEGER,
                    max_weight INTEGER
                )
            ''')
            
            # 创建用户鱼塘表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_fish (
                    user_id TEXT,
                    fish_id INTEGER,
                    quantity INTEGER DEFAULT 0,
                    no_sell_until INTEGER,
                    PRIMARY KEY (user_id, fish_id)
                )
            ''')
            
            # 创建用户鱼饵表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_bait (
                    user_id TEXT,
                    bait_id INTEGER,
                    quantity INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, bait_id)
                )
            ''')
            
            # 创建签到记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS check_ins (
                    user_id TEXT,
                    check_in_date TEXT,
                    PRIMARY KEY (user_id, check_in_date)
                )
            ''')
            
            # 创建补助金记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS subsidies (
                    user_id TEXT,
                    subsidy_date TEXT,
                    PRIMARY KEY (user_id, subsidy_date)
                )
            ''')
            
            # 创建钓鱼记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS fishing_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    fish_id INTEGER,
                    weight INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_special INTEGER DEFAULT 0
                )
            ''')
            
            conn.commit()
    
    def get_user_fish(self, user_id: str) -> List[Dict]:
        """获取用户的鱼塘信息"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT f.id, f.name, f.rarity, uf.quantity, f.base_value,
                       CASE WHEN uf.no_sell_until > strftime('%s', 'now') 
                            THEN uf.no_sell_until - strftime('%s', 'now')
                            ELSE 0 END as lock_time
                FROM user_fish uf
                JOIN fish_config f ON uf.fish_id = f.id
                WHERE uf.user_id = ? AND uf.quantity > 0
                ORDER BY f.rarity DESC, f.base_value DESC
            """, (user_id,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'id': row[0],
                    'name': row[1],
                    'rarity': row[2],
                    'quantity': row[3],
                    'base_value': row[4],
                    'lock_time': row[5]
                })
            return results
    
    def get_user_coins(self, user_id: str) -> int:
        """获取用户金币数量，如果用户不存在则创建"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # 先尝试创建用户
                cursor.execute('''
                    INSERT OR IGNORE INTO user_fishing (user_id, coins)
                    VALUES (?, 100)
                ''', (user_id,))
                conn.commit()
                
                # 然后获取金币数量
                cursor.execute(
                    "SELECT coins FROM user_fishing WHERE user_id = ?",
                    (user_id,)
                )
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logging.error(f"获取用户金币失败: {e}")
            return 0
    
    def has_checked_in_today(self, user_id: str) -> bool:
        """检查用户今天是否已经签到"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM check_ins 
                WHERE user_id = ? AND check_in_date = date('now', 'localtime')
            ''', (user_id,))
            return cursor.fetchone()[0] > 0
    
    def record_check_in(self, user_id: str) -> None:
        """记录用户签到"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO check_ins (user_id, check_in_date)
                VALUES (?, date('now', 'localtime'))
            ''', (user_id,))
            conn.commit()
    
    def update_user_coins(self, user_id: str, amount: int) -> None:
        """更新用户金币"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE user_fishing 
                SET coins = coins + ?
                WHERE user_id = ?
            ''', (amount, user_id))
            conn.commit()
    
    def get_user_current_bait(self, user_id: str) -> Optional[str]:
        """获取用户当前使用的鱼饵"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT current_bait FROM user_fishing WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            return result[0] if result and result[0] else None
    
    def add_user_bait(self, user_id: str, bait_name: str) -> None:
        """添加用户鱼饵"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_bait (user_id, bait_id, quantity)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, bait_id) DO UPDATE
                SET quantity = quantity + 1
            ''', (user_id, bait_name))
            conn.commit()
    
    def show_my_baits(self, user_id: str) -> List[Dict]:
        """查看用户的鱼饵"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT bait_id, quantity FROM user_bait
                WHERE user_id = ? AND quantity > 0
            ''', (user_id,))
            
            return [{"bait_id": row[0], "quantity": row[1]} for row in cursor.fetchall()]
    
    def add_fish_to_pond(self, user_id: str, fish_id: int) -> None:
        """添加鱼到用户鱼塘"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_fish (user_id, fish_id, quantity, no_sell_until)
                VALUES (?, ?, 1, 0)
                ON CONFLICT(user_id, fish_id) DO UPDATE
                SET quantity = quantity + 1
            ''', (user_id, fish_id))
            conn.commit()
    
    def get_bait_info(self, user_id: str) -> Optional[Dict]:
        """获取用户鱼饵信息"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT current_bait, bait_start_time 
                FROM user_fishing 
                WHERE user_id = ? AND current_bait IS NOT NULL
            ''', (user_id,))
            
            result = cursor.fetchone()
            if result and result[0]:
                return {
                    'name': result[0],
                    'start_time': result[1]
                }
            return None
    
    def get_auto_fishing_status(self, user_id: str) -> bool:
        """获取用户自动钓鱼状态"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT auto_fishing FROM user_fishing WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            return bool(result[0]) if result else False
    
    def set_auto_fishing_status(self, user_id: str, status: bool) -> bool:
        """设置用户自动钓鱼状态"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                self._ensure_user_exists(cursor, user_id)  # 确保用户存在
                
                cursor.execute('''
                    UPDATE user_fishing 
                    SET auto_fishing = ? 
                    WHERE user_id = ?
                ''', (1 if status else 0, user_id))
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"设置自动钓鱼状态失败: {e}")
            return False
    
    def get_auto_fishing_users(self) -> List[str]:
        """获取所有开启自动钓鱼的用户"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id FROM user_fishing WHERE auto_fishing = 1"
            )
            return [row[0] for row in cursor.fetchall()]
    
    def get_last_fishing_time(self, user_id: str) -> float:
        """获取用户上次钓鱼时间"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT last_fishing_time FROM user_fishing WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            return float(result[0]) if result and result[0] else 0
    
    def update_last_fishing_time(self, user_id: str) -> None:
        """更新用户上次钓鱼时间"""
        current_time = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE user_fishing 
                SET last_fishing_time = ?
                WHERE user_id = ?
            ''', (current_time, user_id))
            conn.commit()
    
    def get_all_fish_types(self):
        """获取所有鱼类信息"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, name, rarity, base_value FROM fish_config ORDER BY rarity, base_value DESC")
                results = cursor.fetchall()
                
                if not results:
                    return "数据库中没有鱼类信息，请先初始化鱼类数据。"
                
                fish_list = []
                current_rarity = None
                
                for fish in results:
                    fish_id, name, rarity, value = fish
                    
                    # 获取稀有度显示
                    if rarity == 1:
                        rarity_display = "☆垃圾"
                    elif rarity == 2:
                        rarity_display = "☆普通"
                    elif rarity == 3:
                        rarity_display = "☆稀有"
                    elif rarity == 4:
                        rarity_display = "☆史诗"
                    elif rarity == 5:
                        rarity_display = "☆传说"
                    else:
                        rarity_display = f"☆未知({rarity})"
                    
                    # 如果稀有度变化，添加分隔符
                    if current_rarity != rarity:
                        if current_rarity is not None:
                            fish_list.append("")  # 空行分隔不同稀有度
                        fish_list.append(f"【{rarity_display}】")
                        current_rarity = rarity
                    
                    fish_list.append(f"• {name} (ID:{fish_id}) - 价值: {value}金币")
                
                return "\n".join(fish_list)
        except Exception as e:
            logging.error(f"获取鱼类信息失败: {e}", exc_info=True)
            return f"获取鱼类信息失败: {e}"
    
    def initialize_fish_types(self):
        """初始化或更新鱼类数据"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 获取已有鱼类ID
                cursor.execute("SELECT id FROM fish_config")
                existing_ids = {row[0] for row in cursor.fetchall()}
                
                # 定义所有鱼类数据
                fish_data = [
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
                
                # 插入或更新鱼类数据
                for fish in fish_data:
                    fish_id = fish[0]
                    
                    if fish_id in existing_ids:
                        # 更新现有鱼类
                        cursor.execute("""
                            UPDATE fish_config 
                            SET name = ?, rarity = ?, base_value = ?, min_weight = ?, max_weight = ?
                            WHERE id = ?
                        """, (fish[1], fish[2], fish[3], fish[4], fish[5], fish_id))
                    else:
                        # 插入新鱼类
                        cursor.execute("""
                            INSERT INTO fish_config (id, name, rarity, base_value, min_weight, max_weight)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, fish)
                
                conn.commit()
                return f"成功初始化/更新了 {len(fish_data)} 种鱼类数据"
        except Exception as e:
            logging.error(f"初始化鱼类数据失败: {e}", exc_info=True)
            return f"初始化鱼类数据失败: {e}"
    
    def _get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)
    
    def _ensure_user_exists(self, cursor, user_id):
        """确保用户存在于数据库中"""
        cursor.execute('''
            INSERT OR IGNORE INTO user_fishing (user_id, coins)
            VALUES (?, 100)
        ''', (user_id,))
    
    def get_user_fish_quantity(self, user_id: str, fish_id: str) -> int:
        """获取用户特定鱼的数量"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT quantity FROM user_fish
                WHERE user_id = ? AND fish_id = ?
            ''', (user_id, fish_id))
            result = cursor.fetchone()
            return result[0] if result else 0
    
    def remove_fish_from_pond(self, user_id: str, fish_id: str, amount: int) -> None:
        """从鱼塘中移除鱼"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE user_fish
                SET quantity = quantity - ?
                WHERE user_id = ? AND fish_id = ?
            ''', (amount, user_id, fish_id))
            conn.commit()
    
    def clear_user_fish(self, user_id: str) -> None:
        """清空用户鱼塘（但保留锁定的鱼）"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM user_fish
                WHERE user_id = ? AND (no_sell_until IS NULL OR no_sell_until <= strftime('%s', 'now'))
            ''', (user_id,))
            conn.commit()
    
    def get_valuable_fish_list(self, user_id: str) -> List[Dict]:
        """获取用户鱼塘中的高价值鱼"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT f.id, f.name, f.rarity, uf.quantity, f.base_value,
                       CASE WHEN uf.no_sell_until > strftime('%s', 'now') 
                            THEN uf.no_sell_until - strftime('%s', 'now')
                            ELSE 0 END as lock_time
                FROM user_fish uf
                JOIN fish_config f ON uf.fish_id = f.id
                WHERE uf.user_id = ? AND f.rarity >= 3
                ORDER BY f.rarity DESC, f.base_value DESC
            """, (user_id,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'id': row[0],
                    'name': row[1],
                    'rarity': row[2],
                    'quantity': row[3],
                    'base_value': row[4],
                    'lock_time': row[5]
                })
            return results
    
    def set_current_bait(self, user_id: str, bait_name: str) -> None:
        """设置用户当前使用的鱼饵"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            self._ensure_user_exists(cursor, user_id)
            
            if bait_name is None:
                cursor.execute('''
                    UPDATE user_fishing 
                    SET current_bait = NULL, bait_start_time = NULL
                    WHERE user_id = ?
                ''', (user_id,))
            else:
                cursor.execute('''
                    UPDATE user_fishing 
                    SET current_bait = ?, bait_start_time = strftime('%s', 'now')
                    WHERE user_id = ?
                ''', (bait_name, user_id))
            conn.commit()
    
    def use_bait(self, user_id: str, bait_name: str, current_time: float) -> None:
        """使用鱼饵(消耗一个鱼饵并设置为当前使用的鱼饵)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 首先消耗一个鱼饵
            cursor.execute('''
                UPDATE user_bait
                SET quantity = quantity - 1
                WHERE user_id = ? AND bait_id = ? AND quantity > 0
            ''', (user_id, bait_name))
            
            # 然后设置为当前使用的鱼饵
            cursor.execute('''
                UPDATE user_fishing
                SET current_bait = ?, bait_start_time = ?
                WHERE user_id = ?
            ''', (bait_name, current_time, user_id))
            conn.commit()
    
    def get_today_subsidies(self, user_id: str) -> int:
        """获取用户今日领取补助金的次数"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM subsidies 
                WHERE user_id = ? AND subsidy_date = date('now', 'localtime')
            ''', (user_id,))
            return cursor.fetchone()[0]
    
    def record_subsidy(self, user_id: str) -> None:
        """记录用户领取补助金"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO subsidies (user_id, subsidy_date)
                VALUES (?, date('now', 'localtime'))
            ''', (user_id,))
            conn.commit()
