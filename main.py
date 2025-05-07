import os
import logging
import time
import pandas as pd
from PIL.ImagePalette import random

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Node, Plain
from astrbot.api import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.core.star.filter.permission import PermissionType

from .service import FishingService


def get_Node(user_id: str, name: str, message: str) -> Node:
    """将消息转换为Node对象"""
    return Node(uin=user_id, name=name, content=[Plain(message)])


@register("fishing", "Your Name", "一个功能齐全的钓鱼系统插件", "1.0.0",
          "https://github.com/yourusername/astrbot_plugin_fishing")
class FishingPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

        # 初始化数据目录
        self.data_dir = "data/"
        os.makedirs(self.data_dir, exist_ok=True)
        # 初始化数据库和钓鱼系统
        db_path = os.path.join(self.data_dir, "fish.db")
        self.FishingService = FishingService(db_path)

    @filter.command("注册")  # ok
    async def register_user(self, event: AstrMessageEvent):
        """注册钓鱼用户"""
        user_id = event.get_sender_id()
        # 如果用户昵称为空，则使用用户ID
        result = self.FishingService.register(user_id,
                                              event.get_sender_name() if event.get_sender_name() else str(user_id))
        yield event.plain_result(result["message"])

    @filter.command("钓鱼", alias={"fish"})  # ok
    async def go_fishing(self, event: AstrMessageEvent):
        """进行一次钓鱼"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        # 检查CD时间
        last_fishing_time = self.FishingService.db.get_last_fishing_time(user_id)
        current_time = time.time()
        # logger.info(f"用户 {user_id} 上次钓鱼时间: {last_fishing_time}, 当前时间: {current_time}")
        # 3分钟CD (180秒)
        if last_fishing_time > 0 and current_time - last_fishing_time < 180:
            remaining_seconds = int(180 - (current_time - last_fishing_time))
            remaining_minutes = remaining_seconds // 60
            remaining_secs = remaining_seconds % 60
            yield event.plain_result(f"⏳ 钓鱼冷却中，请等待 {remaining_minutes}分{remaining_secs}秒后再试")
            return

        # 钓鱼需要消耗金币
        fishing_cost = 10  # 每次钓鱼消耗10金币
        user_coins = self.FishingService.db.get_user_coins(user_id)

        if user_coins < fishing_cost:
            yield event.plain_result(f"💰 金币不足，钓鱼需要 {fishing_cost} 金币")
            return

        # 扣除金币
        self.FishingService.db.update_user_coins(user_id, -fishing_cost)

        # 进行钓鱼
        result = self.FishingService.fish(user_id)

        # 如果钓鱼成功，显示钓到的鱼的信息
        if result.get("success"):
            fish_info = result.get("fish", {})
            message = f"🎣 恭喜你钓到了 {fish_info.get('name', '未知鱼类')}！\n"
            message += f"✨ 品质：{'★' * fish_info.get('rarity', 1)}\n"
            message += f"⚖️ 重量：{fish_info.get('weight', 0)}g\n"
            message += f"💰 价值：{fish_info.get('value', 0)}金币"
            if isinstance(event, AiocqhttpMessageEvent):
                # 如果是AiocqhttpMessageEvent，使用get_Node函数
                yield event.chain_result([get_Node(event.get_sender_id(), "钓鱼", message)])
            else:
                yield event.plain_result(message)
        else:
            yield event.plain_result(result.get("message", "💨 什么都没钓到..."))

    @filter.command("全部卖出")  # ok
    async def sell_fish(self, event: AstrMessageEvent):
        """出售背包中所有鱼"""
        user_id = event.get_sender_id()
        result = self.FishingService.sell_all_fish(user_id)

        # 替换普通文本消息为带表情的消息
        original_message = result.get("message", "出售失败！")
        if "成功" in original_message:
            # 如果是成功消息，添加成功相关表情
            coins_earned = 0
            if "获得" in original_message:
                # 尝试从消息中提取获得的金币数量
                try:
                    coins_part = original_message.split("获得")[1]
                    coins_str = ''.join(filter(str.isdigit, coins_part))
                    if coins_str:
                        coins_earned = int(coins_str)
                except:
                    pass

            if coins_earned > 0:
                message = f"💰 成功出售所有鱼！获得 {coins_earned} 金币"
            else:
                message = f"💰 {original_message}"
        else:
            # 如果是失败消息，添加失败相关表情
            message = f"❌ {original_message}"

        yield event.plain_result(message)

    @filter.command("出售稀有度", alias={"sellr"})
    async def sell_fish_by_rarity(self, event: AstrMessageEvent):
        """出售特定稀有度的鱼"""
        user_id = event.get_sender_id()
        args = event.message_str.split(' ')

        if len(args) < 2:
            yield event.plain_result("⚠️ 请指定要出售的鱼的稀有度（1-5）")
            return

        try:
            rarity = int(args[1])
            if rarity < 1 or rarity > 5:
                yield event.plain_result("⚠️ 稀有度必须在1-5之间")
                return

            result = self.FishingService.sell_fish_by_rarity(user_id, rarity)

            # 替换普通文本消息为带表情的消息
            original_message = result.get("message", "出售失败！")
            if "成功" in original_message:
                # 如果是成功消息，添加成功相关表情
                coins_earned = 0
                if "获得" in original_message:
                    # 尝试从消息中提取获得的金币数量
                    try:
                        coins_part = original_message.split("获得")[1]
                        coins_str = ''.join(filter(str.isdigit, coins_part))
                        if coins_str:
                            coins_earned = int(coins_str)
                    except:
                        pass

                if coins_earned > 0:
                    message = f"💰 成功出售稀有度 {rarity} 的鱼！获得 {coins_earned} 金币"
                else:
                    message = f"💰 {original_message}"
            else:
                # 如果是失败消息，添加失败相关表情
                message = f"❌ {original_message}"

            yield event.plain_result(message)
        except ValueError:
            yield event.plain_result("⚠️ 请输入有效的稀有度数值（1-5）")

    @filter.command("鱼塘")  # ok
    async def show_inventory(self, event: AstrMessageEvent):
        """显示用户的鱼背包"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        # 获取用户鱼背包
        fish_inventory = self.FishingService.get_fish_pond(user_id)

        if not fish_inventory.get("success"):
            yield event.plain_result(fish_inventory.get("message", "获取背包失败！"))
            return

        fishes = fish_inventory.get("fishes", [])
        total_value = fish_inventory.get("stats", {}).get("total_value", 0)

        if not fishes:
            yield event.plain_result("你的鱼塘是空的，快去钓鱼吧！")
            return

        # 按稀有度分组
        fishes_by_rarity = {}
        for fish in fishes:
            rarity = fish.get("rarity", 1)
            if rarity not in fishes_by_rarity:
                fishes_by_rarity[rarity] = []
            fishes_by_rarity[rarity].append(fish)

        # 构建消息
        message = "【🐟 鱼塘】\n"

        for rarity in sorted(fishes_by_rarity.keys(), reverse=True):
            message += f"\n{'★' * rarity} 稀有度 {rarity}:\n"
            for fish in fishes_by_rarity[rarity]:
                message += f"- {fish.get('name')} x{fish.get('quantity')} ({fish.get('base_value', 0)}金币/个)\n"

        message += f"\n💰 总价值: {total_value}金币"

        if isinstance(event, AiocqhttpMessageEvent):
            # 如果是AiocqhttpMessageEvent，使用get_Node函数
            yield event.chain_result([get_Node(event.get_sender_id(), "鱼塘", message)])
        else:
            yield event.plain_result(message)

    @filter.command("签到", alias={"signin"})  # ok
    async def daily_sign_in(self, event: AstrMessageEvent):
        """每日签到领取奖励"""
        user_id = event.get_sender_id()
        result = self.FishingService.daily_sign_in(user_id)

        # 替换普通文本消息为带表情的消息
        original_message = result.get("message", "签到失败！")
        if "成功" in original_message:
            # 如果是成功消息，添加成功相关表情
            coins_earned = 0
            if "获得" in original_message:
                # 尝试从消息中提取获得的金币数量
                try:
                    coins_part = original_message.split("获得")[1]
                    coins_str = ''.join(filter(str.isdigit, coins_part))
                    if coins_str:
                        coins_earned = int(coins_str)
                except:
                    pass

            if coins_earned > 0:
                message = f"📅 签到成功！获得 {coins_earned} 金币 💰"
            else:
                message = f"📅 {original_message}"
        elif "已经" in original_message and "签到" in original_message:
            # 如果是已经签到的消息
            message = f"📅 你今天已经签到过了，明天再来吧！"
        else:
            # 如果是其他失败消息
            message = f"❌ {original_message}"

        yield event.plain_result(message)

    @filter.command("鱼饵", alias={"baits"})
    async def show_baits(self, event: AstrMessageEvent):
        """显示用户拥有的鱼饵"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        # 获取用户鱼饵
        baits = self.FishingService.get_user_baits(user_id)

        if not baits.get("success"):
            yield event.plain_result(baits.get("message", "获取鱼饵失败！"))
            return

        user_baits = baits.get("baits", [])

        if not user_baits:
            yield event.plain_result("🎣 你没有任何鱼饵，可以通过商店购买！")
            return

        # 构建消息
        message = "【🎣 鱼饵背包】\n"

        has_baits = False
        for bait in user_baits:
            # 只显示数量大于0的鱼饵
            if bait.get("quantity", 0) > 0:
                has_baits = True
                message += f"- {bait.get('name')} x{bait.get('quantity')}"
                if bait.get("effect_description"):
                    message += f" ({bait.get('effect_description')})"
                message += "\n"

        if not has_baits:
            yield event.plain_result("🎣 你没有任何鱼饵，可以通过商店购买！")
            return

        # 获取当前使用的鱼饵
        current_bait = self.FishingService.get_current_bait(user_id)
        if current_bait.get("success") and current_bait.get("bait"):
            bait = current_bait.get("bait")
            message += f"\n⭐ 当前使用的鱼饵: {bait.get('name')}"
            if bait.get("remaining_time"):
                message += f" (⏱️ 剩余时间: {bait.get('remaining_time')}分钟)"

        yield event.plain_result(message)

    @filter.command("使用鱼饵", alias={"usebait"})
    async def use_bait(self, event: AstrMessageEvent):
        """使用特定的鱼饵"""
        user_id = event.get_sender_id()
        args = event.message_str.split(' ')

        if len(args) < 2:
            yield event.plain_result("⚠️ 请指定要使用的鱼饵ID")
            return

        try:
            bait_id = int(args[1])
            result = self.FishingService.use_bait(user_id, bait_id)

            # 增加表情符号
            original_message = result.get("message", "使用鱼饵失败！")
            if "成功" in original_message:
                message = f"🎣 {original_message}"
            else:
                message = f"❌ {original_message}"

            yield event.plain_result(message)
        except ValueError:
            yield event.plain_result("⚠️ 请输入有效的鱼饵ID")

    @filter.command("购买鱼饵", alias={"buybait"})
    async def buy_bait(self, event: AstrMessageEvent):
        """购买鱼饵"""
        user_id = event.get_sender_id()
        args = event.message_str.split(' ')

        if len(args) < 2:
            yield event.plain_result("⚠️ 请指定要购买的鱼饵ID和数量，格式：购买鱼饵 <ID> [数量]")
            return

        try:
            bait_id = int(args[1])

            # 增加数量参数支持
            quantity = 1  # 默认数量为1
            if len(args) >= 3:
                quantity = int(args[2])
                if quantity <= 0:
                    yield event.plain_result("⚠️ 购买数量必须大于0")
                    return

            result = self.FishingService.buy_bait(user_id, bait_id, quantity)

            # 增加表情符号
            original_message = result.get("message", "购买鱼饵失败！")
            if "成功" in original_message:
                message = f"🛒 {original_message}"
            elif "不足" in original_message:
                message = f"💸 {original_message}"
            else:
                message = f"❌ {original_message}"

            yield event.plain_result(message)
        except ValueError:
            yield event.plain_result("⚠️ 请输入有效的鱼饵ID和数量")

    @filter.command("商店", alias={"shop"})
    async def show_shop(self, event: AstrMessageEvent):
        """显示商店中可购买的物品"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        # 获取所有鱼饵
        all_baits = self.FishingService.get_all_baits()

        # 获取所有鱼竿
        all_rods = self.FishingService.get_all_rods()

        # 构建消息
        message = "【🏪 钓鱼商店】\n"

        # 显示鱼饵
        message += "\n【🎣 鱼饵】\n"
        for bait in all_baits.get("baits", []):
            if bait.get("cost", 0) > 0:  # 只显示可购买的
                message += f"ID:{bait.get('bait_id')} - {bait.get('name')} (💰 {bait.get('cost')}金币)"
                if bait.get("description"):
                    message += f" - {bait.get('description')}"
                message += "\n"

        # 显示鱼竿
        message += "\n【🎣 鱼竿】\n"
        for rod in all_rods.get("rods", []):
            if rod.get("source") == "shop" and rod.get("purchase_cost", 0) > 0:
                message += f"ID:{rod.get('rod_id')} - {rod.get('name')} (💰 {rod.get('purchase_cost')}金币)"
                message += f" - 稀有度:{'★' * rod.get('rarity', 1)}"
                if rod.get("bonus_fish_quality_modifier", 1.0) > 1.0:
                    message += f" - 品质加成:⬆️ {int((rod.get('bonus_fish_quality_modifier', 1.0) - 1) * 100)}%"
                if rod.get("bonus_fish_quantity_modifier", 1.0) > 1.0:
                    message += f" - 数量加成:⬆️ {int((rod.get('bonus_fish_quantity_modifier', 1.0) - 1) * 100)}%"
                if rod.get("bonus_rare_fish_chance", 0.0) > 0:
                    message += f" - 稀有度加成:⬆️ {int(rod.get('bonus_rare_fish_chance', 0.0) * 100)}%"
                message += "\n"

        message += "\n💡 使用「购买鱼饵 ID nums」或「购买鱼竿 ID」命令购买物品"

        if isinstance(event, AiocqhttpMessageEvent):
            # 如果是AiocqhttpMessageEvent，使用get_Node函数
            yield event.chain_result([get_Node(event.get_sender_id(), "商店", message)])
        else:
            yield event.plain_result(message)

    @filter.command("购买鱼竿", alias={"buyrod"})
    async def buy_rod(self, event: AstrMessageEvent):
        """购买鱼竿"""
        user_id = event.get_sender_id()
        args = event.message_str.split(' ')

        if len(args) < 2:
            yield event.plain_result("⚠️ 请指定要购买的鱼竿ID")
            return

        try:
            rod_id = int(args[1])
            result = self.FishingService.buy_rod(user_id, rod_id)

            # 增加表情符号
            original_message = result.get("message", "购买鱼竿失败！")
            if "成功" in original_message:
                message = f"🛒 {original_message}"
            elif "不足" in original_message:
                message = f"💸 {original_message}"
            else:
                message = f"❌ {original_message}"

            yield event.plain_result(message)
        except ValueError:
            yield event.plain_result("⚠️ 请输入有效的鱼竿ID")

    @filter.command("使用鱼竿", alias={"userod"})
    async def use_rod(self, event: AstrMessageEvent):
        """装备指定的鱼竿"""
        user_id = event.get_sender_id()
        args = event.message_str.split(' ')

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        if len(args) < 2:
            yield event.plain_result("⚠️ 请指定要装备的鱼竿ID")
            return

        try:
            rod_instance_id = int(args[1])
            result = self.FishingService.equip_rod(user_id, rod_instance_id)

            # 增加表情符号
            original_message = result.get("message", "装备鱼竿失败！")
            if "成功" in original_message:
                message = f"🎣 {original_message}"
            else:
                message = f"❌ {original_message}"

            yield event.plain_result(message)
        except ValueError:
            yield event.plain_result("⚠️ 请输入有效的鱼竿ID")

    @filter.command("鱼竿", alias={"rods"})
    async def show_rods(self, event: AstrMessageEvent):
        """显示用户拥有的鱼竿"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        # 获取用户鱼竿
        rods = self.FishingService.get_user_rods(user_id)

        if not rods.get("success"):
            yield event.plain_result(rods.get("message", "获取鱼竿失败！"))
            return

        user_rods = rods.get("rods", [])

        if not user_rods:
            yield event.plain_result("你没有任何鱼竿，可以通过商店购买！")
            return

        # 构建消息
        message = "【🎣 鱼竿背包】\n"

        # 获取当前装备信息
        equipment_info = self.FishingService.get_user_equipment(user_id)
        if not equipment_info.get("success"):
            # 如果获取装备信息失败，直接显示鱼竿信息，但不标记已装备状态
            for rod in user_rods:
                message += f"ID:{rod.get('rod_instance_id')}- {rod.get('name')} (稀有度:{'★' * rod.get('rarity', 1)})\n"
                if rod.get("description"):
                    message += f"  描述: {rod.get('description')}\n"
                if rod.get("bonus_fish_quality_modifier", 1.0) != 1.0:
                    message += f"  品质加成: {(rod.get('bonus_fish_quality_modifier', 1.0) - 1) * 100:.0f}%\n"
                if rod.get("bonus_fish_quantity_modifier", 1.0) != 1.0:
                    message += f"  数量加成: {(rod.get('bonus_fish_quantity_modifier', 1.0) - 1) * 100:.0f}%\n"
                if rod.get("bonus_rare_fish_chance", 0.0) > 0:
                    message += f"  稀有度加成: +{rod.get('bonus_rare_fish_chance', 0.0) * 100:.0f}%\n"
        else:
            # 正常显示包括已装备状态
            equipped_rod = equipment_info.get("rod")
            equipped_rod_id = equipped_rod.get("rod_instance_id") if equipped_rod else None

            for rod in user_rods:
                rod_instance_id = rod.get("rod_instance_id")
                is_equipped = rod_instance_id == equipped_rod_id or rod.get("is_equipped", False)

                message += f"ID:{rod_instance_id} - {rod.get('name')} (稀有度:{'★' * rod.get('rarity', 1)})"
                if is_equipped:
                    message += " [已装备]"
                message += "\n"
                if rod.get("description"):
                    message += f"  描述: {rod.get('description')}\n"
                if rod.get("bonus_fish_quality_modifier", 1.0) != 1.0:
                    message += f"  品质加成: {(rod.get('bonus_fish_quality_modifier', 1.0) - 1) * 100:.0f}%\n"
                if rod.get("bonus_fish_quantity_modifier", 1.0) != 1.0:
                    message += f"  数量加成: {(rod.get('bonus_fish_quantity_modifier', 1.0) - 1) * 100:.0f}%\n"
                if rod.get("bonus_rare_fish_chance", 0.0) > 0:
                    message += f"  稀有度加成: +{rod.get('bonus_rare_fish_chance', 0.0) * 100:.0f}%\n"

        if isinstance(event, AiocqhttpMessageEvent):
            # 如果是AiocqhttpMessageEvent，使用get_Node函数
            yield event.chain_result([get_Node(event.get_sender_id(), "鱼竿", message)])
        else:
            yield event.plain_result(message)

    @filter.command("抽卡", alias={"gacha"})
    async def do_gacha(self, event: AstrMessageEvent):
        """进行单次抽卡"""
        user_id = event.get_sender_id()
        args = event.message_str.split(' ')

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        if len(args) < 2:
            # 获取所有抽卡池
            pools = self.FishingService.get_all_gacha_pools()
            if pools.get("success"):
                message = "【🎮 可用的抽卡池】\n\n"
                for pool in pools.get("pools", []):
                    message += f"ID:{pool.get('gacha_pool_id')} - {pool.get('name')}"
                    if pool.get("description"):
                        message += f" - {pool.get('description')}"
                    message += "\n"
                    message += f"    💰 花费: {pool.get('cost_coins')}金币/次\n\n"

                # 添加卡池详细信息
                message += "【📋 卡池详情】使用「查看卡池 ID」命令查看详细物品概率\n"
                message += "【🎲 抽卡命令】使用「抽卡 ID」命令选择抽卡池进行单次抽卡\n"
                message += "【🎯 十连命令】使用「十连 ID」命令进行十连抽卡"
                if isinstance(event, AiocqhttpMessageEvent):
                    # 如果是AiocqhttpMessageEvent，使用get_Node函数
                    yield event.chain_result([get_Node(event.get_sender_id(), "抽卡池", message)])
                else:
                    yield event.plain_result(message)
                return
            else:
                yield event.plain_result("❌ 获取抽卡池失败！")
                return

        try:
            pool_id = int(args[1])
            result = self.FishingService.gacha(user_id, pool_id)

            if result.get("success"):
                item = result.get("item", {})

                # 根据稀有度添加不同的表情
                rarity = item.get('rarity', 1)
                rarity_emoji = "✨" if rarity >= 4 else "🌟" if rarity >= 3 else "⭐" if rarity >= 2 else "🔹"

                message = f"{rarity_emoji} 抽卡结果: {item.get('name', '未知物品')}"
                if item.get("rarity"):
                    message += f" (稀有度:{'★' * item.get('rarity', 1)})"
                if item.get("quantity", 1) > 1:
                    message += f" x{item.get('quantity', 1)}"
                message += "\n"

                # 获取物品的详细信息
                item_type = item.get('type')
                item_id = item.get('id')

                # 根据物品类型获取详细信息
                details = None
                if item_type == 'rod':
                    details = self.FishingService.db.get_rod_info(item_id)
                elif item_type == 'accessory':
                    details = self.FishingService.db.get_accessory_info(item_id)
                elif item_type == 'bait':
                    details = self.FishingService.db.get_bait_info(item_id)

                # 显示物品描述
                if details and details.get('description'):
                    message += f"📝 描述: {details.get('description')}\n"

                # 显示物品属性
                if details:
                    # 显示品质加成
                    quality_modifier = details.get('bonus_fish_quality_modifier', 1.0)
                    if quality_modifier > 1.0:
                        message += f"✨ 品质加成: +{(quality_modifier - 1) * 100:.0f}%\n"

                    # 显示数量加成
                    quantity_modifier = details.get('bonus_fish_quantity_modifier', 1.0)
                    if quantity_modifier > 1.0:
                        message += f"📊 数量加成: +{(quantity_modifier - 1) * 100:.0f}%\n"

                    # 显示稀有度加成
                    rare_chance = details.get('bonus_rare_fish_chance', 0.0)
                    if rare_chance > 0:
                        message += f"🌟 稀有度加成: +{rare_chance * 100:.0f}%\n"

                    # 显示效果说明(鱼饵)
                    if item_type == 'bait' and details.get('effect_description'):
                        message += f"🎣 效果: {details.get('effect_description')}\n"

                    # 显示饰品特殊效果
                    if item_type == 'accessory' and details.get('other_bonus_description'):
                        message += f"🔮 特殊效果: {details.get('other_bonus_description')}\n"

                if isinstance(event, AiocqhttpMessageEvent):
                    # 如果是AiocqhttpMessageEvent，使用get_Node函数
                    yield event.chain_result([get_Node(event.get_sender_id(), "抽卡", message)])
                else:
                    yield event.plain_result(message)
            else:
                original_message = result.get("message", "抽卡失败！")
                if "不足" in original_message:
                    yield event.plain_result(f"💸 {original_message}")
                else:
                    yield event.plain_result(f"❌ {original_message}")
        except ValueError:
            yield event.plain_result("⚠️ 请输入有效的抽卡池ID")

    @filter.command("查看卡池", alias={"pool"})
    async def view_gacha_pool(self, event: AstrMessageEvent):
        """查看卡池详细信息"""
        user_id = event.get_sender_id()
        args = event.message_str.split(' ')

        if len(args) < 2:
            yield event.plain_result("请指定要查看的卡池ID，如：查看卡池 1")
            return

        try:
            pool_id = int(args[1])
            pool_details = self.FishingService.db.get_gacha_pool_details(pool_id)

            if not pool_details:
                yield event.plain_result(f"卡池ID:{pool_id} 不存在")
                return

            message = f"【{pool_details.get('name')}】{pool_details.get('description', '')}\n\n"
            message += f"抽取花费: {pool_details.get('cost_coins', 0)}金币\n\n"

            message += "可抽取物品:\n"
            # 按稀有度分组
            items_by_rarity = {}
            for item in pool_details.get('items', []):
                rarity = item.get('item_rarity', 1)
                if rarity not in items_by_rarity:
                    items_by_rarity[rarity] = []
                items_by_rarity[rarity].append(item)

            # 按稀有度从高到低显示
            for rarity in sorted(items_by_rarity.keys(), reverse=True):
                message += f"\n稀有度 {rarity} ({'★' * rarity}):\n"
                for item in items_by_rarity[rarity]:
                    item_name = item.get('item_name', f"{item.get('item_type')}_{item.get('item_id')}")
                    probability = item.get('probability', 0)
                    quantity = item.get('quantity', 1)

                    if item.get('item_type') == 'coins':
                        item_name = f"{quantity}金币"
                    elif quantity > 1:
                        item_name = f"{item_name} x{quantity}"

                    message += f"- {item_name} ({probability:.2f}%)\n"

                    # 添加物品描述
                    item_description = item.get('item_description')
                    if item_description:
                        message += f"  描述: {item_description}\n"

                    # 添加属性加成信息
                    item_type = item.get('item_type')
                    if item_type in ['rod', 'accessory']:
                        # 品质加成
                        quality_modifier = item.get('quality_modifier', 1.0)
                        if quality_modifier > 1.0:
                            message += f"  品质加成: +{(quality_modifier - 1) * 100:.0f}%\n"

                        # 数量加成
                        quantity_modifier = item.get('quantity_modifier', 1.0)
                        if quantity_modifier > 1.0:
                            message += f"  数量加成: +{(quantity_modifier - 1) * 100:.0f}%\n"

                        # 稀有度加成
                        rare_chance = item.get('rare_chance', 0.0)
                        if rare_chance > 0:
                            message += f"  稀有度加成: +{rare_chance * 100:.0f}%\n"

                    # 添加效果说明
                    effect_description = item.get('effect_description')
                    if effect_description:
                        message += f"  效果: {effect_description}\n"
            if isinstance(event, AiocqhttpMessageEvent):
                # 如果是AiocqhttpMessageEvent，使用get_Node函数
                yield event.chain_result([get_Node(event.get_sender_id(), "卡池详情", message)])
            else:
                yield event.plain_result(message)

        except ValueError:
            yield event.plain_result("请输入有效的卡池ID")

    @filter.command("十连", alias={"multi"})
    async def do_multi_gacha(self, event: AstrMessageEvent):
        """进行十连抽卡"""
        user_id = event.get_sender_id()
        args = event.message_str.split(' ')

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        if len(args) < 2:
            yield event.plain_result("⚠️ 请指定要抽卡的池子ID")
            return

        try:
            pool_id = int(args[1])
            result = self.FishingService.multi_gacha(user_id, pool_id)

            if result.get("success"):
                results = result.get("results", [])
                rewards_by_rarity = result.get("rewards_by_rarity", {})
                message = "【🎮 十连抽卡结果】\n\n"

                # 先显示高稀有度的物品
                for rarity in sorted(rewards_by_rarity.keys(), reverse=True):
                    items = rewards_by_rarity[rarity]

                    # 根据稀有度显示不同的表情
                    rarity_emoji = "✨" if rarity >= 4 else "🌟" if rarity >= 3 else "⭐" if rarity >= 2 else "🔹"
                    message += f"{rarity_emoji} 稀有度 {rarity} ({'★' * rarity}):\n"

                    for item in items:
                        item_name = item.get('name', '未知物品')
                        quantity = item.get('quantity', 1)

                        if quantity > 1:
                            message += f"- {item_name} x{quantity}\n"
                        else:
                            message += f"- {item_name}\n"

                        # 获取物品的详细信息
                        item_type = item.get('type')
                        item_id = item.get('id')

                        # 只为稀有度3及以上的物品显示详细信息
                        if rarity >= 3:
                            details = None
                            if item_type == 'rod':
                                details = self.FishingService.db.get_rod_info(item_id)
                            elif item_type == 'accessory':
                                details = self.FishingService.db.get_accessory_info(item_id)
                            elif item_type == 'bait':
                                details = self.FishingService.db.get_bait_info(item_id)

                            # 显示物品描述
                            if details and details.get('description'):
                                message += f"  📝 描述: {details.get('description')}\n"

                            # 显示物品属性
                            if details:
                                # 显示品质加成
                                quality_modifier = details.get('bonus_fish_quality_modifier', 1.0)
                                if quality_modifier > 1.0:
                                    message += f"  ✨ 品质加成: +{(quality_modifier - 1) * 100:.0f}%\n"

                                # 显示数量加成
                                quantity_modifier = details.get('bonus_fish_quantity_modifier', 1.0)
                                if quantity_modifier > 1.0:
                                    message += f"  📊 数量加成: +{(quantity_modifier - 1) * 100:.0f}%\n"

                                # 显示稀有度加成
                                rare_chance = details.get('bonus_rare_fish_chance', 0.0)
                                if rare_chance > 0:
                                    message += f"  🌟 稀有度加成: +{rare_chance * 100:.0f}%\n"

                                # 显示效果说明(鱼饵)
                                if item_type == 'bait' and details.get('effect_description'):
                                    message += f"  🎣 效果: {details.get('effect_description')}\n"

                                # 显示饰品特殊效果
                                if item_type == 'accessory' and details.get('other_bonus_description'):
                                    message += f"  🔮 特殊效果: {details.get('other_bonus_description')}\n"

                    message += "\n"
                if isinstance(event, AiocqhttpMessageEvent):
                    # 如果是AiocqhttpMessageEvent，使用get_Node函数
                    yield event.chain_result([get_Node(event.get_sender_id(), "十连抽卡", message)])
                else:
                    yield event.plain_result(message)
            else:
                original_message = result.get("message", "十连抽卡失败！")
                if "不足" in original_message:
                    yield event.plain_result(f"💸 {original_message}")
                else:
                    yield event.plain_result(f"❌ {original_message}")
        except ValueError:
            yield event.plain_result("⚠️ 请输入有效的抽卡池ID")

    @filter.command("金币", alias={"coins"})
    async def check_coins(self, event: AstrMessageEvent):
        """查看用户金币数量"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        # 获取用户货币信息
        result = self.FishingService.get_user_currency(user_id)

        if not result.get("success"):
            yield event.plain_result("获取货币信息失败！")
            return

        coins = result.get("coins", 0)

        message = f"💰 你的金币: {coins}"
        yield event.plain_result(message)

    @filter.command("排行榜", alias={"rank"})
    async def show_ranking(self, event: AstrMessageEvent):
        """显示钓鱼排行榜"""
        try:
            # 查询排行榜数据
            top_users = self.FishingService.db.get_leaderboard(limit=10)

            if not top_users:
                yield event.plain_result("📊 暂无排行榜数据，快去争当第一名吧！")
                return

            message = "【🏆 钓鱼排行榜 - TOP 10】\n\n"

            # 显示金币排行
            message += "💰 金币富豪榜 💰\n"
            for idx, user in enumerate(sorted(top_users, key=lambda x: x.get('coins', 0), reverse=True)[:10], 1):
                # 添加排名表情
                rank_emoji = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
                message += f"{rank_emoji} {user.get('nickname', '未知用户')} - {user.get('coins', 0)}金币\n"

            message += "\n🎣 钓鱼大师榜 🎣\n"
            for idx, user in enumerate(
                    sorted(top_users, key=lambda x: x.get('total_fishing_count', 0), reverse=True)[:10], 1):
                rank_emoji = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
                message += f"{rank_emoji} {user.get('nickname', '未知用户')} - {user.get('total_fishing_count', 0)}条鱼\n"

            message += "\n⚖️ 总重量榜 ⚖️\n"
            for idx, user in enumerate(
                    sorted(top_users, key=lambda x: x.get('total_weight_caught', 0), reverse=True)[:10], 1):
                rank_emoji = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
                message += f"{rank_emoji} {user.get('nickname', '未知用户')} - {user.get('total_weight_caught', 0)}g\n"

            if isinstance(event, AiocqhttpMessageEvent):
                # 如果是AiocqhttpMessageEvent，使用get_Node函数
                yield event.chain_result([get_Node(event.get_sender_id(), "排行榜", message)])
            else:
                yield event.plain_result(message)
        except Exception as e:
            logger.error(f"获取排行榜失败: {e}")
            yield event.plain_result(f"❌ 获取排行榜时出错，请稍后再试！")

    @filter.command("自动钓鱼", alias={"auto"})
    async def toggle_auto_fishing(self, event: AstrMessageEvent):
        """开启或关闭自动钓鱼"""
        user_id = event.get_sender_id()
        result = self.FishingService.toggle_auto_fishing(user_id)

        # 增加表情符号
        original_message = result.get("message", "操作失败！")
        if "开启" in original_message:
            message = f"🤖 {original_message}"
        elif "关闭" in original_message:
            message = f"⏹️ {original_message}"
        else:
            message = f"❌ {original_message}"

        yield event.plain_result(message)

    @filter.command("钓鱼帮助", alias={"钓鱼指南"})
    async def show_help(self, event: AstrMessageEvent):
        """显示钓鱼游戏帮助信息"""
        prefix = """前言：使用/注册指令即可开始，鱼饵是一次性的（每次钓鱼随机使用），可以一次买多个鱼饵例如：/购买鱼饵 3 200。鱼竿购买后可以通过/鱼竿查看，如果你嫌钓鱼慢，可以玩玩/擦弹 金币数量，随机获得0-10倍收益"""
        message = """【🎣 钓鱼系统帮助】
    📋 基础命令:
     - /注册: 注册钓鱼用户
     - /钓鱼: 进行一次钓鱼(消耗10金币，5分钟CD)
     - /签到: 每日签到领取奖励
     - /金币: 查看当前金币
    
    🎒 背包相关:
     - /鱼塘: 查看鱼类背包
     - /鱼饵: 查看鱼饵背包
     - /鱼竿: 查看鱼竿背包
    
    🏪 商店与购买:
     - /商店: 查看可购买的物品
     - /购买鱼饵 ID [数量]: 购买指定ID的鱼饵，可选择数量
     - /购买鱼竿 ID: 购买指定ID的鱼竿
     - /使用鱼饵 ID: 使用指定ID的鱼饵
     - /使用鱼竿 ID: 装备指定ID的鱼竿
    
    💰 出售鱼类:
     - /全部卖出: 出售背包中所有鱼
     - /出售稀有度 <1-5>: 出售特定稀有度的鱼
    
    🎮 抽卡系统:
     - /抽卡 ID: 进行单次抽卡
     - /十连 ID: 进行十连抽卡
     - /查看卡池 ID: 查看卡池详细信息和概率
    
    🔧 其他功能:
     - /自动钓鱼: 开启/关闭自动钓鱼功能
     - /排行榜: 查看钓鱼排行榜
     - /鱼类图鉴: 查看所有鱼的详细信息
     - /擦弹 [金币数]: 向公共奖池投入金币，获得随机倍数回报
     - /擦弹历史： 查看擦弹历史记录
     - /查看称号: 查看已获得的称号
     - /查看成就: 查看可达成的成就
     - /钓鱼记录: 查看最近的钓鱼记录
    """
        message = prefix + "\n" + message
        if isinstance(event, AiocqhttpMessageEvent):
            # 如果是AiocqhttpMessageEvent，使用get_Node函数
            yield event.chain_result([get_Node(event.get_sender_id(), "钓鱼帮助", message)])
        else:
            yield event.plain_result(message)

    @filter.command("鱼类图鉴", alias={"鱼图鉴", "图鉴"})
    async def show_fish_catalog(self, event: AstrMessageEvent):
        """显示所有鱼的图鉴"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        # 调用服务获取所有鱼类信息
        cursor = self.FishingService.db._get_connection().cursor()
        cursor.execute("""
            SELECT fish_id, name, description, rarity, base_value, min_weight, max_weight
            FROM fish
            ORDER BY rarity DESC, base_value DESC
        """)
        fishes = cursor.fetchall()

        if not fishes:
            yield event.plain_result("鱼类图鉴中暂无数据")
            return

        # 按稀有度分组
        fishes_by_rarity = {}
        for fish in fishes:
            rarity = fish['rarity']
            if rarity not in fishes_by_rarity:
                fishes_by_rarity[rarity] = []
            fishes_by_rarity[rarity].append(dict(fish))

        # 构建消息
        message = "【📖 鱼类图鉴】\n\n"

        for rarity in sorted(fishes_by_rarity.keys(), reverse=True):
            message += f"★ 稀有度 {rarity} ({'★' * rarity}):\n"

            # 只显示每个稀有度的前5条，太多会导致消息过长
            fish_list = fishes_by_rarity[rarity][:5]
            for fish in fish_list:
                message += f"- {fish['name']} (💰 价值: {fish['base_value']}金币)\n"
                if fish['description']:
                    message += f"  📝 {fish['description']}\n"
                message += f"  ⚖️ 重量范围: {fish['min_weight']}~{fish['max_weight']}g\n"

            # 如果该稀有度鱼类超过5种，显示省略信息
            if len(fishes_by_rarity[rarity]) > 5:
                message += f"  ... 等共{len(fishes_by_rarity[rarity])}种\n"

            message += "\n"

        # 添加总数统计和提示
        total_fish = sum(len(group) for group in fishes_by_rarity.values())
        message += f"📊 图鉴收录了共计 {total_fish} 种鱼类。\n"
        message += "💡 提示：钓鱼可能会钓到鱼以外的物品，比如各种特殊物品和神器！"

        yield event.plain_result(message)

    @filter.command("擦弹", alias={"wipe"})
    async def do_wipe_bomb(self, event: AstrMessageEvent):
        """进行擦弹，投入金币并获得随机倍数的奖励"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        # 解析参数
        args = event.message_str.split(' ')

        if len(args) < 2:
            yield event.plain_result("💸 请指定要投入的金币数量，例如：擦弹 100")
            return

        try:
            amount = int(args[1])
            if amount <= 0:
                yield event.plain_result("⚠️ 投入金币必须大于0")
                return

            # 调用服务执行擦弹操作
            result = self.FishingService.perform_wipe_bomb(user_id, amount)

            # 替换普通文本消息为带表情的消息
            original_message = result.get("message", "擦弹失败，请稍后再试")

            if "成功" in original_message:
                # 尝试从结果中提取倍数和奖励
                multiplier = result.get("multiplier", 0)
                reward = result.get("reward", 0)
                profit = reward - amount

                if multiplier > 0:
                    # 根据倍数和盈利情况选择不同的表情
                    if multiplier >= 2:
                        if profit > 0:
                            message = f"🎰 大成功！你投入 {amount} 金币，获得了 {multiplier}倍 回报！\n💰 奖励: {reward} 金币 (盈利: +{profit})"
                        else:
                            message = f"🎰 你投入 {amount} 金币，获得了 {multiplier}倍 回报！\n💰 奖励: {reward} 金币 (亏损: {profit})"
                    else:
                        if profit > 0:
                            message = f"🎲 你投入 {amount} 金币，获得了 {multiplier}倍 回报！\n💰 奖励: {reward} 金币 (盈利: +{profit})"
                        else:
                            message = f"💸 你投入 {amount} 金币，获得了 {multiplier}倍 回报！\n💰 奖励: {reward} 金币 (亏损: {profit})"
                else:
                    message = f"🎲 {original_message}"
            else:
                # 如果是失败消息
                if "不足" in original_message:
                    message = f"💸 金币不足，无法进行擦弹"
                else:
                    message = f"❌ {original_message}"

            if isinstance(event, AiocqhttpMessageEvent):
                # 如果是AiocqhttpMessageEvent，使用get_Node函数
                yield event.chain_result([get_Node(event.get_sender_id(), "擦弹", message)])
            else:
                yield event.plain_result(message)

        except ValueError:
            yield event.plain_result("⚠️ 请输入有效的金币数量")

    @filter.command("擦弹历史", alias={"wipe_history"})
    async def show_wipe_history(self, event: AstrMessageEvent):
        """显示用户的擦弹历史记录"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        # 获取擦弹历史
        result = self.FishingService.get_wipe_bomb_history(user_id)

        if not result.get("success"):
            yield event.plain_result("❌ 获取擦弹历史失败")
            return

        records = result.get("records", [])

        if not records:
            yield event.plain_result("📝 你还没有进行过擦弹操作")
            return

        # 构建消息
        message = "【📊 擦弹历史记录】\n\n"

        for idx, record in enumerate(records, 1):
            timestamp = record.get('timestamp', '未知时间')
            contribution = record.get('contribution_amount', 0)
            multiplier = record.get('reward_multiplier', 0)
            reward = record.get('reward_amount', 0)
            profit = record.get('profit', 0)

            # 根据盈亏状况显示不同表情
            if profit > 0:
                profit_text = f"📈 盈利 {profit}"
                if multiplier >= 2:
                    emoji = "🎉"  # 高倍率盈利用庆祝表情
                else:
                    emoji = "✅"  # 普通盈利用勾选表情
            else:
                profit_text = f"📉 亏损 {-profit}"
                emoji = "💸"  # 亏损用钱飞走表情

            message += f"{idx}. ⏱️ {timestamp}\n"
            message += f"   {emoji} 投入: {contribution} 金币，获得 {multiplier}倍 ({reward} 金币)\n"
            message += f"   {profit_text}\n"

        # 添加是否可以再次擦弹的提示
        can_wipe_today = result.get("available_today", False)
        if can_wipe_today:
            message += "\n🎮 今天你还可以进行擦弹"
        else:
            message += "\n⏳ 今天你已经进行过擦弹了，明天再来吧"

        if isinstance(event, AiocqhttpMessageEvent):
            # 如果是AiocqhttpMessageEvent，使用get_Node函数
            yield event.chain_result([get_Node(event.get_sender_id(), "擦弹历史", message)])
        else:
            yield event.plain_result(message)

    @filter.command("查看称号", alias={"称号", "titles"})
    async def show_titles(self, event: AstrMessageEvent):
        """显示用户已获得的称号"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        # 获取用户称号
        result = self.FishingService.get_user_titles(user_id)

        if not isinstance(result, dict) or not result.get("success", False):
            yield event.plain_result("获取称号信息失败")
            return

        titles = result.get("titles", [])

        if not titles:
            yield event.plain_result("🏆 你还没有获得任何称号，努力完成成就以获取称号吧！")
            return

        # 构建消息
        message = "【🏆 已获得称号】\n\n"

        for title in titles:
            message += f"- {title.get('name')}\n"
            if title.get('description'):
                message += f"  📝 {title.get('description')}\n"

        message += "\n💡 提示：完成特定成就可以获得更多称号！"

        if isinstance(event, AiocqhttpMessageEvent):
            # 如果是AiocqhttpMessageEvent，使用get_Node函数
            yield event.chain_result([get_Node(event.get_sender_id(), "称号", message)])
        else:
            yield event.plain_result(message)

    @filter.command("查看成就", alias={"成就", "achievements"})
    async def show_achievements(self, event: AstrMessageEvent):
        """显示用户的成就进度"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        if not self.FishingService.is_registered(user_id):
            yield event.plain_result("请先注册才能使用此功能")
            return

        # 获取成就进度（这里需要修改FishingService添加获取成就进度的方法）
        # 临时解决方案：直接从数据库查询
        try:
            user_progress = self.FishingService.db.get_user_achievement_progress(user_id)

            if not user_progress:
                # 如果没有进度记录，至少显示一些可用的成就
                cursor = self.FishingService.db._get_connection().cursor()
                cursor.execute("""
                    SELECT achievement_id, name, description, target_type, target_value, reward_type, reward_value
                    FROM achievements
                    LIMIT 10
                """)
                achievements = [dict(row) for row in cursor.fetchall()]

                message = "【🏅 成就列表】\n\n"
                message += "你还没有开始任何成就的进度，这里是一些可以完成的成就：\n\n"

                for ach in achievements:
                    message += f"- {ach['name']}: {ach['description']}\n"
                    message += f"  🎯 目标: {ach['target_value']} ({ach['target_type']})\n"
                    reward_text = f"{ach['reward_type']} (ID: {ach['reward_value']})"
                    message += f"  🎁 奖励: {reward_text}\n"

                yield event.plain_result(message)
                return

            # 筛选出有进度的成就和完成但未领取奖励的成就
            in_progress = []
            completed = []

            for progress in user_progress:
                is_completed = progress.get('completed_at') is not None
                is_claimed = progress.get('claimed_at') is not None

                if is_completed and not is_claimed:
                    completed.append(progress)
                elif progress.get('current_progress', 0) > 0:
                    in_progress.append(progress)

            # 构建消息
            message = "【🏅 成就进度】\n\n"

            if completed:
                message += "✅ 已完成但未领取奖励的成就:\n"
                for ach in completed:
                    message += f"- {ach['name']}: {ach['description']}\n"
                    reward_text = f"{ach['reward_type']} (ID: {ach['reward_value']})"
                    message += f"  🎁 奖励: {reward_text}\n"
                message += "\n"

            if in_progress:
                message += "⏳ 进行中的成就:\n"
                for ach in in_progress:
                    progress_percent = min(100, int(ach['current_progress'] / ach['target_value'] * 100))
                    message += f"- {ach['name']} ({progress_percent}%)\n"
                    message += f"  📝 {ach['description']}\n"
                    message += f"  📊 进度: {ach['current_progress']}/{ach['target_value']}\n"
                message += "\n"

            if not completed and not in_progress:
                message += "你还没有进行中的成就，继续钓鱼和使用其他功能来完成成就吧！\n"

            message += "💡 提示：完成成就可以获得各种奖励，包括金币、称号、特殊物品等！"

            if isinstance(event, AiocqhttpMessageEvent):
                # 如果是AiocqhttpMessageEvent，使用get_Node函数
                yield event.chain_result([get_Node(event.get_sender_id(), "成就进度", message)])
            else:
                yield event.plain_result(message)

        except Exception as e:
            logger.error(f"获取成就进度失败: {e}")
            yield event.plain_result("获取成就进度时出错，请稍后再试")

    @filter.command("钓鱼记录", "查看记录")
    async def fishing_records(self, event: AstrMessageEvent):
        """查看钓鱼记录"""
        user_id = event.get_sender_id()

        result = self.FishingService.get_user_fishing_records(user_id)
        if not result["success"]:
            yield event.plain_result(result["message"])
            return

        records = result["records"]
        if not records:
            yield event.plain_result("📝 你还没有任何钓鱼记录，快去钓鱼吧！")
            return

        # 格式化记录显示
        message = "【📝 最近钓鱼记录】\n"
        for idx, record in enumerate(records, 1):
            time_str = record.get('timestamp', '未知时间')
            if isinstance(time_str, str) and len(time_str) > 16:
                time_str = time_str[:16]  # 简化时间显示

            fish_name = record.get('fish_name', '未知鱼类')
            rarity = record.get('rarity', 0)
            weight = record.get('weight', 0)
            value = record.get('value', 0)

            rod_name = record.get('rod_name', '无鱼竿')
            bait_name = record.get('bait_name', '无鱼饵')

            # 稀有度星星显示
            rarity_stars = '★' * rarity

            # 判断是否为大型鱼
            king_size = "👑 " if record.get('is_king_size', 0) else ""

            message += f"{idx}. ⏱️ {time_str} {king_size}{fish_name} {rarity_stars}\n"
            message += f"   ⚖️ 重量: {weight}g | 💰 价值: {value}金币\n"
            message += f"   🔧 装备: {rod_name} | 🎣 鱼饵: {bait_name}\n"
        if isinstance(event, AiocqhttpMessageEvent):
            # 如果是AiocqhttpMessageEvent，使用get_Node函数
            yield event.chain_result([get_Node(event.get_sender_id(), "钓鱼记录", message)])
        else:
            yield event.plain_result(message)
    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("用户列表", alias={"users"})
    async def show_all_users(self, event: AstrMessageEvent):
        """显示所有注册用户的信息"""
        try:
            # 获取所有用户ID
            all_users = self.FishingService.db.get_all_users()
            
            if not all_users:
                yield event.plain_result("📊 暂无注册用户")
                return

            # 构建消息
            message = "【👥 用户列表】\n\n"
            
            # 获取每个用户的详细信息
            for idx, user_id in enumerate(all_users, 1):
                # 获取用户基本信息
                user_stats = self.FishingService.db.get_user_fishing_stats(user_id)
                user_currency = self.FishingService.db.get_user_currency(user_id)
                
                if not user_stats or not user_currency:
                    continue
                
                # 获取用户昵称
                cursor = self.FishingService.db._get_connection().cursor()
                cursor.execute("SELECT nickname FROM users WHERE user_id = ?", (user_id,))
                result = cursor.fetchone()
                nickname = result[0] if result else "未知用户"
                
                # 获取用户装备信息
                equipment = self.FishingService.db.get_user_equipment(user_id)
                rod_name = equipment.get("rod", {}).get("name", "无鱼竿") if equipment.get("success") else "无鱼竿"
                
                # 获取用户鱼塘信息
                fish_inventory = self.FishingService.db.get_user_fish_inventory(user_id)
                total_fish = sum(fish.get("quantity", 0) for fish in fish_inventory)
                
                # 格式化用户信息
                message += f"{idx}. 👤 {nickname} (ID: {user_id})\n"
                message += f"   💰 金币: {user_currency.get('coins', 0)}\n"
                message += f"   🎣 钓鱼次数: {user_stats.get('total_fishing_count', 0)}\n"
                message += f"   🐟 鱼塘数量: {total_fish}\n"
                message += f"   ⚖️ 总重量: {user_stats.get('total_weight_caught', 0)}g\n"
                message += f"   🎯 当前装备: {rod_name}\n"
                message += "\n"

            # 添加统计信息
            total_users = len(all_users)
            message += f"📊 总用户数: {total_users}"

            if isinstance(event, AiocqhttpMessageEvent):
                # 如果是AiocqhttpMessageEvent，使用get_Node函数
                yield event.chain_result([get_Node(event.get_sender_id(), "用户列表", message)])
            else:
                yield event.plain_result(message)
                
        except Exception as e:
            logger.error(f"获取用户列表失败: {e}")
            yield event.plain_result(f"❌ 获取用户列表时出错，请稍后再试！错误信息：{str(e)}")

    @filter.command("钓鱼赛季总结")
    async def fishing_season_summary(self, event: AstrMessageEvent):
        """查看钓鱼赛季总结"""
        user_id = event.get_sender_id()

        try:
            # 从 user_stats_20250506.csv 中读取数据
            df = pd.read_csv("data/plugins/astrbot_plugin_fishing/user_stats_20250506.csv")

            # 将用户ID转换为字符串以确保匹配
            df['用户ID'] = df['用户ID'].astype(str)
            user_id_str = str(user_id)

            # 过滤出当前用户的数据
            user_data = df[df['用户ID'] == user_id_str]

            if user_data.empty:
                yield event.plain_result("没有找到你的钓鱼赛季数据")
                return

            # 提取数据
            total_check_in = user_data['签到天数'].values[0]
            coins = user_data['金币数'].values[0]
            lottery_counts = user_data['抽奖次数'].values[0]
            lottery_coins = user_data['抽奖总金额'].values[0]

            # 计算排名
            total_users = len(df)
            coins_rank = df[df['金币数'] >= coins].shape[0]
            check_in_rank = df[df['签到天数'] >= total_check_in].shape[0]
            lottery_count_rank = df[df['抽奖次数'] >= lottery_counts].shape[0]
            lottery_coins_rank = df[df['抽奖总金额'] >= lottery_coins].shape[0]

            # 计算每个指标的百分位
            coins_percentile = (total_users - coins_rank + 1) / total_users * 100
            checkin_percentile = (total_users - check_in_rank + 1) / total_users * 100
            lottery_count_percentile = (total_users - lottery_count_rank + 1) / total_users * 100
            lottery_coins_percentile = (total_users - lottery_coins_rank + 1) / total_users * 100

            # 构建消息
            message = f"【🏆 钓鱼赛季总结】\n\n"
            message += f"🎉 你在本赛季的表现如下：\n"

            # 签到天数评价
            message += f"📅 签到天数: {total_check_in}天 (排名: {check_in_rank}/{total_users})\n"
            if checkin_percentile >= 90:
                message += f"   🌟 你的签到非常勤奋，超过了{checkin_percentile:.1f}%的玩家！\n"
            elif checkin_percentile >= 70:
                message += f"   ✨ 你的签到相当稳定，超过了{checkin_percentile:.1f}%的玩家。\n"
            elif checkin_percentile >= 50:
                message += f"   👍 你的签到尚可，继续保持！\n"
            else:
                message += f"   💡 要记得每天签到哦，这样可以获得更多金币。\n"

            # 金币评价
            message += f"💰 总金币数: {coins}金币 (排名: {coins_rank}/{total_users})\n"
            if coins_percentile >= 90:
                message += f"   💎 你是钓鱼大富翁，财富超过了{coins_percentile:.1f}%的玩家！\n"
            elif coins_percentile >= 70:
                message += f"   🏅 你的财富相当可观，超过了{coins_percentile:.1f}%的玩家。\n"
            elif coins_percentile >= 50:
                message += f"   👍 你的金币数量处于中上水平。\n"
            else:
                message += f"   💪 继续努力钓鱼和参与活动，可以积累更多金币。\n"

            # 抽奖次数评价
            message += f"🎲 抽奖次数: {int(lottery_counts)}次 (排名: {lottery_count_rank}/{total_users})\n"
            if lottery_count_percentile >= 90:
                message += f"   🎯 你是抽奖狂热者，抽奖次数超过了{lottery_count_percentile:.1f}%的玩家！\n"
            elif lottery_count_percentile >= 70:
                message += f"   🎪 你很喜欢抽奖，次数超过了{lottery_count_percentile:.1f}%的玩家。\n"
            elif lottery_count_percentile >= 50:
                message += f"   👍 你对抽奖有一定的兴趣。\n"
            else:
                message += f"   💡 多参与抽奖，也许会有意外收获哦！\n"

            # 抽奖总金币评价
            message += f"💸 抽奖总金币: {int(lottery_coins)}金币 (排名: {lottery_coins_rank}/{total_users})\n"
            if lottery_coins_percentile >= 90:
                message += f"   🌈 你的抽奖运气非常好，收益超过了{lottery_coins_percentile:.1f}%的玩家！\n"
            elif lottery_coins_percentile >= 70:
                message += f"   🍀 你的抽奖运气不错，收益超过了{lottery_coins_percentile:.1f}%的玩家。\n"
            elif lottery_coins_percentile >= 50:
                message += f"   👍 你的抽奖收益处于中上水平。\n"
            else:
                message += f"   🎯 运气有起伏，下次抽奖也许会有更好的收获！\n"

            # 总体评价
            message += "\n【🏆 总体评价】\n"
            avg_percentile = (
                                         coins_percentile + checkin_percentile + lottery_count_percentile + lottery_coins_percentile) / 4

            if avg_percentile >= 90:
                message += "你是本赛季的顶尖玩家，在各方面都表现出色，继续保持这样的水平！"
            elif avg_percentile >= 70:
                message += "你在本赛季表现优秀，是资深的钓鱼玩家，相信下个赛季会更好！"
            elif avg_percentile >= 50:
                message += "你在本赛季表现不错，继续努力可以更上一层楼！"
            else:
                message += "感谢你参与本赛季活动，希望在下个赛季看到你的进步！"

            if isinstance(event, AiocqhttpMessageEvent):
                # 如果是AiocqhttpMessageEvent，使用get_Node函数
                yield event.chain_result([get_Node(event.get_sender_id(), "钓鱼赛季总结", message)])
            else:
                yield event.plain_result(message)
        except Exception as e:
            logger.error(f"生成钓鱼赛季总结失败: {e}")
            yield event.plain_result(f"❌ 生成赛季总结时出错，请稍后再试！错误信息：{str(e)}")

    async def terminate(self):
        """插件被卸载/停用时调用"""
        logger.info("钓鱼插件正在终止...")
        # 停止自动钓鱼线程
        self.FishingService.stop_auto_fishing_task()
