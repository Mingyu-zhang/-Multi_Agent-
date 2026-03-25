"""
快速使用示例 - 三省六部制 Multi-Agent 系统
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from core.system import create_system


async def demo_basic():
    """基础对话示例"""
    print("=" * 60)
    print("示例1：基础对话（Mock LLM）")
    print("=" * 60)

    system = await create_system("mock")

    questions = [
        "帮我写一首关于秋天的五言律诗",
        "分析一下三省六部制的历史意义",
        "帮我制定一个Python学习计划",
    ]

    for q in questions:
        print(f"\n👤 用户: {q}")
        reply = await system.ask(q, from_user="demo_user")
        print(f"🏛️  系统: {reply}")

    await system.stop()


async def demo_with_openai():
    """使用 OpenAI 的示例"""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("未设置 OPENAI_API_KEY 环境变量，跳过此示例")
        return

    print("=" * 60)
    print("示例2：使用 OpenAI GPT-4o")
    print("=" * 60)

    system = await create_system("openai", api_key=api_key, model="gpt-4o")
    reply = await system.ask("请介绍一下中国古代三省六部制度")
    print(f"🏛️  回复: {reply}")
    await system.stop()


async def demo_custom_tool():
    """自定义工具示例（给兵部注册工具）"""
    print("=" * 60)
    print("示例3：注册自定义工具")
    print("=" * 60)

    system = await create_system("mock")

    # 给兵部注册一个计算工具
    async def calculator(expression: str) -> str:
        try:
            result = eval(expression, {"__builtins__": {}})
            return f"计算结果: {expression} = {result}"
        except Exception as e:
            return f"计算失败: {e}"

    system.register_tool("calculator", calculator)

    reply = await system.ask("请计算 123 * 456 + 789")
    print(f"🏛️  回复: {reply}")

    await system.stop()


async def demo_switch_llm():
    """热切换LLM示例"""
    print("=" * 60)
    print("示例4：运行时切换LLM")
    print("=" * 60)

    from core.llm import MockLLM
    system = await create_system("mock", response="我是第一个Mock回复")
    print("当前LLM:", system.llm)

    reply1 = await system.ask("你好")
    print(f"回复1: {reply1}")

    # 切换到另一个Mock
    new_llm = MockLLM(response="我是切换后的Mock回复")
    system.switch_llm(new_llm)
    print("切换后LLM:", system.llm)

    reply2 = await system.ask("你好")
    print(f"回复2: {reply2}")

    await system.stop()


if __name__ == "__main__":
    asyncio.run(demo_basic())
    # asyncio.run(demo_with_openai())  # 需要设置 OPENAI_API_KEY
    # asyncio.run(demo_custom_tool())
    # asyncio.run(demo_switch_llm())
