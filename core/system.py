"""
系统主入口 & 工厂函数
三省六部 Multi-Agent 系统
"""
from __future__ import annotations
import asyncio
from typing import Optional, Dict

from core.base import MessageBus
from core.llm import BaseLLM, create_llm, MockLLM
from agents.sansheng_liubu import (
    ZhongShuAgent, MenXiaAgent, ShangShuAgent,
    LiBuAgent, HuBuAgent, LiBu2Agent, BingBuAgent, XingBuAgent, GongBuAgent,
    TianZiGateway,
)


class SanShengLiuBuSystem:
    """
    三省六部制 Multi-Agent 系统
    ─────────────────────────────────
    使用示例：
        sys = SanShengLiuBuSystem(llm=create_llm("openai", api_key="sk-..."))
        await sys.start()
        reply = await sys.ask("帮我写一首关于秋天的诗")
        print(reply)
    """

    def __init__(self, llm: Optional[BaseLLM] = None,
                 llm_config: Optional[Dict] = None):
        """
        :param llm: 已创建好的LLM实例（优先使用）
        :param llm_config: LLM配置字典 {"provider": "openai", "api_key": "...", ...}
        """
        if llm is None and llm_config:
            provider = llm_config.pop("provider", "mock")
            llm = create_llm(provider, **llm_config)
        elif llm is None:
            llm = MockLLM()

        self.llm = llm
        self.bus = MessageBus()

        # 实例化三省
        self.zhongshu = ZhongShuAgent(self.bus, llm)
        self.menxia = MenXiaAgent(self.bus, llm)
        self.shangshu = ShangShuAgent(self.bus, llm)

        # 实例化六部
        self.libu = LiBuAgent(self.bus, llm)
        self.hubu = HuBuAgent(self.bus, llm)
        self.libu2 = LiBu2Agent(self.bus, llm)
        self.bingbu = BingBuAgent(self.bus, llm)
        self.xingbu = XingBuAgent(self.bus, llm)
        self.gongbu = GongBuAgent(self.bus, llm)

        # 天子门户
        self.gateway = TianZiGateway(self.bus, self.libu2)

        self._bus_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动系统"""
        self._bus_task = asyncio.create_task(self.bus.start())
        print("[OK] 三省六部制 Multi-Agent 系统已启动")
        print(f"   LLM后端: {self.llm}")
        print("   三省: 中书省 -> 门下省 -> 尚书省")
        print("   六部: 吏部 户部 礼部 兵部 刑部 工部")

    async def stop(self):
        """关闭系统"""
        self.bus.stop()
        if self._bus_task:
            self._bus_task.cancel()
        print("系统已关闭")

    async def ask(self, content: str, from_user: str = "user",
                  im_platform: str = "console") -> str:
        """
        向系统提问（同步等待回复）
        :param content: 用户输入
        :param from_user: 用户标识
        :param im_platform: 来源平台标识
        :return: 系统最终回复
        """
        return await self.gateway.ask(content, from_user, im_platform)

    def register_tool(self, name: str, func):
        """给兵部注册工具"""
        self.bingbu.register_tool(name, func)

    def register_im_output(self, platform: str, callback):
        """给礼部注册IM输出回调（用于非阻塞模式）"""
        self.libu2.register_output(platform, callback)

    def switch_llm(self, llm: BaseLLM):
        """热切换LLM后端"""
        self.llm = llm
        for agent in [self.zhongshu, self.menxia, self.shangshu,
                      self.libu, self.hubu, self.libu2,
                      self.bingbu, self.xingbu, self.gongbu]:
            agent.llm = llm
        print(f"[OK] LLM已切换为: {llm}")

    def get_history(self, session_id: str = None):
        """获取消息历史"""
        return self.bus.get_history(session_id)


# ─── 快速启动 ─────────────────────────────────────────────────────────────────

async def create_system(provider: str = "mock", **llm_kwargs) -> SanShengLiuBuSystem:
    """
    快速创建并启动系统

    示例：
        # 使用OpenAI
        sys = await create_system("openai", api_key="sk-...", model="gpt-4o")

        # 使用本地Ollama
        sys = await create_system("ollama", model="qwen2")

        # 使用Mock（测试）
        sys = await create_system("mock")
    """
    llm = create_llm(provider, **llm_kwargs)
    system = SanShengLiuBuSystem(llm=llm)
    await system.start()
    return system
