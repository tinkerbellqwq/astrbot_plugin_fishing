from typing import Dict, Tuple, Optional, List
import random
import time
import threading
import logging
from .db import FishingDB
from .constants import *
from .fish import Fish
from .stats import FisherStats, BestCatch
from .lottery import FishingLottery

class FishingSystem:
    def __init__(self, config: Dict, get_nickname_func):
        self.config = config
        self.db = FishingDB(config['database'])
        self.get_nickname = get_nickname_func
        self.lottery = FishingLottery(self.db)
        self.LOG = logging.getLogger("Fishing")
        self.current_weather = None
        self.last_weather_update = 0
        self.update_weather()
        self.fish_db: Dict[str, List[Fish]] = {}  # user_id -> fish list
        self.auto_fishing: Dict[str, bool] = {}   # user_id -> is_auto_fishing
        self.last_fish_time: Dict[str, float] = {}  # user_id -> last_fish_time
        self.last_steal_time: Dict[str, float] = {}  # user_id -> last_steal_time
        
        # 读取自动钓鱼配置
        self.auto_fishing_enabled = config.get('auto_fishing_enabled', True)
        self.LOG.info(f"自动钓鱼功能: {'已启用' if self.auto_fishing_enabled else '已禁用'}")
        
        # 初始化自动钓鱼线程
        self.auto_fishing_thread = None
        
        # 启动自动钓鱼任务
        if self.auto_fishing_enabled:
            self.start_auto_fishing_task()
        else:
            self.LOG.info("自动钓鱼功能已禁用，不启动自动钓鱼任务")
            
        # 初始化鱼类数据库
        if config.get('initialize_fish_types', True):
            self.LOG.info("初始化鱼类数据库...")
            self._initialize_fish_types()
    
    def update_weather(self) -> None:
        """更新天气"""
        current_time = time.time()
        if current_time - self.last_weather_update >= self.config.get('weather_update_interval', 3600):
            self.current_weather = random.choice(WEATHER_TYPES)
            self.last_weather_update = current_time
    
    def show_help(self) -> str:
        """显示帮助信息"""
        return """🎣 钓鱼帮助 🎣

基础命令：
🎯 /钓鱼：开始钓鱼（消耗50金币）
🌊 /鱼塘：查看已捕获的鱼
🎯 /自动钓鱼：开启/关闭自动钓鱼
✨ /钓鱼签到：每日领取金币

交易系统：
💰 /卖鱼 <鱼名> <数量>：出售指定鱼获得金币
📦 /全部卖出：一次性卖出所有鱼

鱼饵系统：
🏪 /鱼饵商城：查看可购买的鱼饵
🛒 /购买鱼饵 <名称>：购买指定鱼饵
🎯 /使用鱼饵 <名称>：使用指定鱼饵
📦 /我的鱼饵：查看拥有的鱼饵

💡 小贴士：
1. 新用户会获得100金币的起始资金
2. 每次钓鱼需要消耗50金币
3. 钓鱼和自动钓鱼CD为5分钟
4. 使用鱼饵可以提高钓鱼成功率
5. 稀有度越高的鱼价值越高
6. 每天记得签到领取金币"""

    def get_weather_info(self) -> str:
        """获取天气信息"""
        self.update_weather()
        weather = self.current_weather
        weather_effects = {
            '晴天': {'success_rate': 0.7, 'cost_modifier': 1.0},
            '阴天': {'success_rate': 0.6, 'cost_modifier': 1.0},
            '雨天': {'success_rate': 0.5, 'cost_modifier': 1.05},
            '暴雨': {'success_rate': 0.3, 'cost_modifier': 1.1},
            '极光': {'success_rate': 0.6, 'cost_modifier': 1.1},
            '潮汐': {'success_rate': 0.8, 'cost_modifier': 0.9}
        }
        effects = weather_effects.get(weather, {'success_rate': 0.5, 'cost_modifier': 1.0})
        success_rate = effects.get('success_rate', 0.5)
        cost_modifier = effects.get('cost_modifier', 1.0)
        
        return f"""🌤️ 当前天气：{weather}
成功率：{int(success_rate * 100)}%
费用修正：{int(cost_modifier * 100)}%"""

    def fish(self, user_id: str, is_auto: bool = False) -> str:
        """钓鱼主函数"""
        # 检查CD时间
        current_time = time.time()
        last_time = self.db.get_last_fishing_time(user_id)
        cd_time = 300  # 设置300秒CD (5分钟)
        
        if current_time - last_time < cd_time and not is_auto:
            remaining = int(cd_time - (current_time - last_time))
            minutes = remaining // 60
            seconds = remaining % 60
            cd_msg = f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒"
            return f"⏳ CD中，还需等待{cd_msg}"
        
        # 检查用户金币
        user_coins = self.db.get_user_coins(user_id)
        cost = self.get_fishing_cost()
        if user_coins < cost:
            return f"金币不足，需要{cost}金币"
        
        # 更新最后钓鱼时间
        self.db.update_last_fishing_time(user_id)
        
        # 扣除金币
        self.db.update_user_coins(user_id, -cost)
        
        # 计算成功率并尝试钓鱼
        success_rate = self.calculate_success_rate(user_id)
        if random.random() < success_rate:
            fish = self.get_random_fish()
            if fish:
                self.db.add_fish_to_pond(user_id, fish['id'])
                message = f"""🎣 {fish['grade_display']} 恭喜钓到了
【{fish['name']}】{self.get_rarity_stars(fish['rarity'])}
⚖️ 重量：{fish['weight']}kg
💰 价值：{fish['value']}金币
💨 消耗金币：{cost}"""
                return message
        
        return "💨 什么都没钓到..."

    def calculate_success_rate(self, user_id: str) -> float:
        """计算钓鱼成功率"""
        base_rate = 0.7  # 基础成功率70%
        bait_effect = self.get_bait_effect(user_id)
        return min(base_rate + bait_effect, 0.95)  # 最高95%成功率

    def get_fishing_cost(self) -> int:
        """计算钓鱼成本"""
        return self.config.get('base_cost', 50)  # 默认成本50金币

    def daily_check_in(self, user_id: str) -> str:
        """每日签到"""
        # 检查是否已经签到
        if self.db.has_checked_in_today(user_id):
            return "❌ 今天已经签到过了，明天再来吧！"
            
        # 随机奖励金币 (50-200)
        coins = random.randint(50, 200)
        self.db.update_user_coins(user_id, coins)
        self.db.record_check_in(user_id)
        
        # 获取用户当前金币
        total_coins = self.db.get_user_coins(user_id)
        
        return f"""✨ 签到成功！
获得金币：{coins}
当前金币：{total_coins}"""

    def get_bait_effect(self, user_id: str) -> float:
        """获取用户当前使用的鱼饵效果"""
        bait_info = self.db.get_bait_info(user_id)
        if not bait_info:
            return 0.0
        
        # 检查是否过期
        bait_name = bait_info['name']
        start_time = bait_info['start_time']
        
        # 计算鱼饵是否在有效期内
        current_time = time.time()
        if not start_time or not BAIT_DATA.get(bait_name):
            return 0.0
            
        duration = BAIT_DATA[bait_name]['duration']
        if current_time - float(start_time) > duration:
            # 清除过期的鱼饵
            self.db.set_current_bait(user_id, None)
            return 0.0
        
        return BAIT_DATA[bait_name]['effect']

    def set_user_coins(self, user_id: str, coins: int) -> str:
        """设置用户金币"""
        self.db.update_user_coins(user_id, coins)
        return f"✅ v给用户 {user_id} 的金币为 {coins}"

    def get_random_fish(self) -> Dict:
        """获取随机鱼"""
        # 随机选择鱼类等级，基于稀有度概率
        rarity_probs = {
            1: 0.40,  # 垃圾 40%
            2: 0.30,  # 普通 30%
            3: 0.20,  # 稀有 20%
            4: 0.08,  # 史诗 8%
            5: 0.02   # 传说 2%
        }
        
        # 根据概率随机选择稀有度
        rarity = self._weighted_choice(list(rarity_probs.items()))
        
        # 获取该稀有度的所有鱼
        fish_with_rarity = {}
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, base_value, min_weight, max_weight FROM fish_config WHERE rarity = ?", (rarity,))
            for row in cursor.fetchall():
                fish_id, name, base_value, min_weight, max_weight = row
                fish_with_rarity[fish_id] = {
                    'id': fish_id,
                    'name': name,
                    'rarity': rarity,
                    'base_value': base_value,
                    'min_weight': min_weight,
                    'max_weight': max_weight
                }
        
        if not fish_with_rarity:
            return None
            
        # 随机选择一条鱼
        fish_id = random.choice(list(fish_with_rarity.keys()))
        fish = fish_with_rarity[fish_id]
        
        # 随机生成重量
        weight = random.uniform(fish['min_weight'] / 1000, fish['max_weight'] / 1000)
        weight = round(weight, 2)  # 保留两位小数
        
        # 计算价值（基础价值 * 重量修正）
        value = int(fish['base_value'] * (1 + (weight - fish['min_weight']/1000) / (fish['max_weight']/1000 - fish['min_weight']/1000) * 0.5))
        
        # 获取品级显示
        grade_display = self.get_grade_display(rarity)
        
        return {
            'id': fish['id'],
            'name': fish['name'],
            'rarity': rarity,
            'weight': weight,
            'value': value,
            'grade_display': grade_display
        }

    def show_bait_shop(self) -> str:
        """显示鱼饵商城"""
        baits = BAIT_DATA
        
        shop_info = ["🏪 鱼饵商城 🏪\n"]
        
        for name, data in baits.items():
            duration_mins = data['duration'] // 60
            shop_info.append(f"🎣 {name}")
            shop_info.append(f"💰 价格: {data['price']}金币")
            shop_info.append(f"⬆️ 效果: 提升钓鱼成功率{int(data['effect']*100)}%")
            shop_info.append(f"⏱️ 持续: {duration_mins}分钟")
            shop_info.append(f"📝 描述: {data['description']}")
            shop_info.append("")
        
        shop_info.append("购买方式: /购买鱼饵 <名称>")
        return "\n".join(shop_info)

    def buy_bait(self, user_id: str, bait_name: str) -> str:
        """购买鱼饵"""
        # 检查鱼饵是否存在
        if bait_name not in BAIT_DATA:
            return f"❌ 没有找到名为「{bait_name}」的鱼饵"
        
        # 获取鱼饵价格
        price = BAIT_DATA[bait_name]['price']
        
        # 检查用户金币是否足够
        user_coins = self.db.get_user_coins(user_id)
        if user_coins < price:
            return f"❌ 金币不足，需要{price}金币，当前持有{user_coins}金币"
        
        # 扣除金币并添加鱼饵
        self.db.update_user_coins(user_id, -price)
        self.db.add_user_bait(user_id, bait_name)
        
        return f"""✅ 成功购买鱼饵「{bait_name}」
💰 花费: {price}金币
💰 剩余: {user_coins - price}金币

使用方法: /使用鱼饵 {bait_name}"""

    def get_user_fish_pond(self, user_id: str) -> str:
        """获取用户鱼塘信息"""
        fish_list = self.db.get_user_fish(user_id)
        
        if not fish_list:
            return "🌊 你的鱼塘空空如也，快去钓鱼吧！"
        
        # 获取用户金币
        coins = self.db.get_user_coins(user_id)
        
        result = [f"🌊 {self.get_nickname(user_id)}的鱼塘 | 💰{coins}金币"]
        result.append("-" * 20)
        
        # 按稀有度分组
        fish_by_rarity = {}
        for fish in fish_list:
            rarity = fish['rarity']
            if rarity not in fish_by_rarity:
                fish_by_rarity[rarity] = []
            fish_by_rarity[rarity].append(fish)
        
        # 按稀有度从高到低显示
        for rarity in sorted(fish_by_rarity.keys(), reverse=True):
            rarity_text = {1: "垃圾", 2: "普通", 3: "稀有", 4: "史诗", 5: "传说"}.get(rarity, "未知")
            result.append(f"【{rarity_text}】{self.get_rarity_stars(rarity)}")
            
            for fish in fish_by_rarity[rarity]:
                lock_time = fish.get('lock_time', 0)
                lock_status = f" 🔒{int(lock_time//60)}分钟" if lock_time > 0 else ""
                result.append(f"• {fish['name']} x{fish['quantity']} 💰{fish['base_value']}金币{lock_status}")
            
            result.append("")
        
        result.append("💡 卖鱼指令: /卖鱼 <鱼名> <数量>")
        result.append("💡 一键卖出: /全部卖出")
        
        return "\n".join(result)

    def show_my_baits(self, user_id: str) -> str:
        """查看用户拥有的鱼饵"""
        baits = self.db.show_my_baits(user_id)
        
        if not baits:
            return "📦 你没有任何鱼饵，可以通过「/鱼饵商城」购买"
        
        result = ["📦 我的鱼饵"]
        result.append("-" * 20)
        
        for bait in baits:
            bait_id = bait['bait_id']
            quantity = bait['quantity']
            if bait_id in BAIT_DATA:
                effect = BAIT_DATA[bait_id]['effect']
                duration_mins = BAIT_DATA[bait_id]['duration'] // 60
                result.append(f"🎣 {bait_id} x{quantity}")
                result.append(f"⬆️ 效果: 提升成功率{int(effect*100)}%")
                result.append(f"⏱️ 持续: {duration_mins}分钟")
                result.append("")
            else:
                result.append(f"🎣 {bait_id} x{quantity} (未知鱼饵)")
                result.append("")
        
        result.append("使用方法: /使用鱼饵 <名称>")
        
        return "\n".join(result)

    def use_bait(self, user_id: str, bait_name: str) -> str:
        """使用鱼饵"""
        # 检查鱼饵是否存在
        if bait_name not in BAIT_DATA:
            return f"❌ 没有找到名为「{bait_name}」的鱼饵"
        
        # 检查用户是否拥有这种鱼饵
        baits = self.db.show_my_baits(user_id)
        has_bait = False
        
        for bait in baits:
            if bait['bait_id'] == bait_name and bait['quantity'] > 0:
                has_bait = True
                break
        
        if not has_bait:
            return f"❌ 你没有「{bait_name}」，可以通过「/鱼饵商城」购买"
        
        # 使用鱼饵
        current_time = time.time()
        self.db.use_bait(user_id, bait_name, current_time)
        
        effect = BAIT_DATA[bait_name]['effect']
        duration_mins = BAIT_DATA[bait_name]['duration'] // 60
        
        return f"""🎣 成功使用「{bait_name}」
⬆️ 效果: 提升钓鱼成功率{int(effect*100)}%
⏱️ 持续时间: {duration_mins}分钟"""

    def sell_fish(self, user_id: str, fish_name: str, amount: int) -> str:
        """卖鱼获得金币"""
        if amount <= 0:
            return "❌ 请输入正确的数量"
        
        # 查找鱼的ID
        fish_id = None
        fish_value = 0
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, base_value FROM fish_config WHERE name = ?", (fish_name,))
            result = cursor.fetchone()
            if result:
                fish_id, fish_value = result
            else:
                return f"❌ 没有找到名为「{fish_name}」的鱼"
        
        # 获取用户的这种鱼的数量
        owned_amount = self.db.get_user_fish_quantity(user_id, fish_id)
        if owned_amount < amount:
            return f"❌ 你只有{owned_amount}条「{fish_name}」，不够卖{amount}条"
        
        # 检查是否有锁定的鱼
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT no_sell_until FROM user_fish
                WHERE user_id = ? AND fish_id = ? AND no_sell_until > strftime('%s', 'now')
            """, (user_id, fish_id))
            locked = cursor.fetchone()
            if locked:
                lock_time = int(locked[0]) - int(time.time())
                minutes = lock_time // 60
                seconds = lock_time % 60
                return f"❌ 「{fish_name}」处于禁售期，还有{minutes}分{seconds}秒解除"
        
        # 计算总价值
        total_value = fish_value * amount
        
        # 更新数据库
        self.db.remove_fish_from_pond(user_id, fish_id, amount)
        self.db.update_user_coins(user_id, total_value)
        
        user_coins = self.db.get_user_coins(user_id)
        
        return f"""💰 成功出售 {amount}条「{fish_name}」
💰 获得: {total_value}金币
💰 当前金币: {user_coins}"""

    def sell_all_fish(self, user_id: str) -> str:
        """卖出所有非锁定的鱼"""
        fish_list = self.db.get_user_fish(user_id)
        
        if not fish_list:
            return "🌊 你的鱼塘空空如也，没有可卖出的鱼"
        
        total_sold = 0
        total_value = 0
        sold_fish = []
        
        for fish in fish_list:
            # 跳过锁定的鱼
            if fish.get('lock_time', 0) > 0:
                continue
                
            fish_id = fish['id']
            quantity = fish['quantity']
            name = fish['name']
            value = fish['base_value'] * quantity
            
            # 从鱼塘中移除并增加金币
            self.db.remove_fish_from_pond(user_id, fish_id, quantity)
            self.db.update_user_coins(user_id, value)
            
            total_sold += quantity
            total_value += value
            sold_fish.append(f"• {name} x{quantity} ({value}金币)")
        
        if total_sold == 0:
            return "❌ 没有可卖出的鱼，可能都处于禁售期"
        
        user_coins = self.db.get_user_coins(user_id)
        
        result = [f"💰 成功出售 {total_sold}条鱼，获得{total_value}金币"]
        result.append(f"💰 当前金币: {user_coins}")
        result.append("\n出售明细:")
        result.extend(sold_fish)
        
        return "\n".join(result)

    def sell_by_rarity(self, user_id: str, rarity: int) -> str:
        """按稀有度等级卖出鱼"""
        # 获取用户所有鱼
        fish_list = self.db.get_user_fish(user_id)
        
        if not fish_list:
            return "🌊 你的鱼塘空空如也，没有可卖出的鱼"
        
        # 过滤出指定稀有度的鱼
        target_fish = [fish for fish in fish_list if fish['rarity'] == rarity]
        
        if not target_fish:
            rarity_names = {1: "垃圾", 2: "普通", 3: "稀有", 4: "史诗", 5: "传说"}
            return f"❌ 没有{rarity_names.get(rarity, '未知')}品质的鱼可卖出"
        
        total_sold = 0
        total_value = 0
        sold_fish = []
        
        for fish in target_fish:
            # 跳过锁定的鱼
            if fish.get('lock_time', 0) > 0:
                continue
                
            fish_id = fish['id']
            quantity = fish['quantity']
            name = fish['name']
            value = fish['base_value'] * quantity
            
            # 从鱼塘中移除并增加金币
            self.db.remove_fish_from_pond(user_id, fish_id, quantity)
            self.db.update_user_coins(user_id, value)
            
            total_sold += quantity
            total_value += value
            sold_fish.append(f"• {name} x{quantity} ({value}金币)")
        
        if total_sold == 0:
            rarity_names = {1: "垃圾", 2: "普通", 3: "稀有", 4: "史诗", 5: "传说"}
            return f"❌ 所有{rarity_names.get(rarity, '未知')}品质的鱼都处于禁售期"
        
        user_coins = self.db.get_user_coins(user_id)
        rarity_names = {1: "垃圾", 2: "普通", 3: "稀有", 4: "史诗", 5: "传说"}
        
        result = [f"💰 成功出售 {total_sold}条{rarity_names.get(rarity, '未知')}品质的鱼，获得{total_value}金币"]
        result.append(f"💰 当前金币: {user_coins}")
        result.append("\n出售明细:")
        result.extend(sold_fish)
        
        return "\n".join(result)

    def toggle_auto_fishing(self, user_id: str) -> str:
        """开启/关闭自动钓鱼"""
        if not self.auto_fishing_enabled:
            return "❌ 自动钓鱼功能已被管理员禁用"
            
        current_status = self.db.get_auto_fishing_status(user_id)
        new_status = not current_status
        
        if new_status:
            # 检查金币是否足够
            user_coins = self.db.get_user_coins(user_id)
            if user_coins < self.get_fishing_cost():
                return f"❌ 金币不足，无法开启自动钓鱼，最少需要{self.get_fishing_cost()}金币"
        
        self.db.set_auto_fishing_status(user_id, new_status)
        
        if new_status:
            return """✅ 自动钓鱼已开启
⏱️ 每5分钟自动钓鱼一次
💰 每次消耗50金币
📝 可随时关闭: /自动钓鱼"""
        else:
            return "✅ 自动钓鱼已关闭"

    def start_auto_fishing_task(self):
        """启动自动钓鱼任务"""
        if self.auto_fishing_thread and self.auto_fishing_thread.is_alive():
            self.LOG.info("自动钓鱼线程已在运行中")
            return
            
        self.auto_fishing_thread = threading.Thread(target=self._auto_fishing_loop, daemon=True)
        self.auto_fishing_thread.start()
        self.LOG.info("自动钓鱼线程已启动")

    def _auto_fishing_loop(self):
        """自动钓鱼循环任务"""
        while True:
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
                            self.LOG.info(f"用户 {user_id} 自动钓鱼结果: {result[:30]}...")
                            
                        except Exception as e:
                            self.LOG.error(f"用户 {user_id} 自动钓鱼出错: {e}")
                
                # 每分钟检查一次
                time.sleep(60)
                
            except Exception as e:
                self.LOG.error(f"自动钓鱼任务出错: {e}", exc_info=True)
                time.sleep(60)  # 出错后等待1分钟再重试

    def get_rarity_stars(self, rarity: int) -> str:
        """获取稀有度星星显示"""
        return "⭐" * rarity
        
    def get_grade_display(self, rarity: int) -> str:
        """获取等级显示文本"""
        displays = {
            1: "【C】⭐",
            2: "【N】⭐⭐",
            3: "【R】⭐⭐⭐",
            4: "【SR】⭐⭐⭐⭐",
            5: "【SSR】⭐⭐⭐⭐⭐"
        }
        return displays.get(rarity, f"【?】{'⭐' * rarity}")


    def get_subsidy(self, user_id: str) -> str:
        """领取补助金"""
        # 检查用户当前金币
        current_coins = self.db.get_user_coins(user_id)
        if current_coins >= 50:
            return "❌ 您的金币已经超过50，无法领取补助金"
        
        # 检查今日领取次数
        today_subsidies = self.db.get_today_subsidies(user_id)
        if today_subsidies >= 3:
            return "❌ 今日补助金领取次数已达上限（3次）"
        
        # 发放补助金（200金币）
        subsidy_amount = 200
        self.db.update_user_coins(user_id, subsidy_amount)
        self.db.record_subsidy(user_id)
        
        # 获取更新后的金币数
        new_coins = self.db.get_user_coins(user_id)
        
        return f"""✨ 补助金领取成功！
获得金币：{subsidy_amount}
当前金币：{new_coins}
今日剩余领取次数：{2 - today_subsidies}"""

    def _weighted_choice(self, choices):
        """基于权重的随机选择"""
        # choices是一个(选项, 权重)的列表
        total = sum(weight for _, weight in choices)
        r = random.uniform(0, total)
        upto = 0
        for item, weight in choices:
            if upto + weight >= r:
                return item
            upto += weight
        # 如果循环结束还没返回（不应该发生），返回最后一项
        return choices[-1][0]

    def _initialize_fish_types(self):
        """初始化鱼类数据库"""
        self.db.initialize_fish_types()
