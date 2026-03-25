"""
三省六部制 Agent 实现
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
三省：
  - 中书省（ZhongShu）：拟旨起草，接收用户请求，分析意图，生成任务方案
  - 门下省（MenXia） ：审驳封驳，审查中书省方案，把关质量，可否决
  - 尚书省（ShangShu）：统领六部，执行调度，汇总结果上报

六部（隶属尚书省）：
  - 吏部（LiBu）    ：人员/Agent管理，权限分配
  - 户部（HuBu）    ：数据与资源管理，文件/数据库操作
  - 礼部（LiBu2）   ：协议与格式，对外接口适配（IM消息格式化）
  - 兵部（BingBu）  ：任务调度与执行，工具调用，代码运行
  - 刑部（XingBu）  ：异常处理，错误追踪，安全审查
  - 工部（GongBu）  ：基础建设，搜索/爬虫/外部API调用
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import asyncio
import json
from typing import Any, Dict, Optional

from core.base import BaseAgent, Message, MessageBus, MessageType, Priority


# ─── 中书省 ───────────────────────────────────────────────────────────────────

class ZhongShuAgent(BaseAgent):
    """
    中书省 - 草拟诏令
    职责：接收用户请求 → 分析意图 → 生成结构化任务 → 下发给门下省审核
    """

    SYSTEM_PROMPT = """你是三省六部制AI系统的中书省，负责接收用户请求并起草行动方案。
你的职责：
1. 准确理解用户意图
2. 将请求分解为具体任务
3. 起草详细的任务规划书，包含：任务目标、执行步骤、所需资源、预期结果
4. 任务规划需考虑周全，用JSON格式输出

输出格式示例：
{
  "task_title": "任务名称",
  "intent": "用户意图摘要",
  "steps": [
    {"id": 1, "dept": "户部/兵部/工部等", "action": "具体操作", "params": {}}
  ],
  "priority": "normal/high/urgent",
  "estimated_output": "预期结果描述"
}"""

    def __init__(self, bus: MessageBus, llm=None):
        super().__init__("zhongshu", "中书省", bus, llm, self.SYSTEM_PROMPT)

    async def handle(self, message: Message):
        """处理用户输入，起草任务方案"""
        if message.msg_type == MessageType.USER_INPUT:
            # 调用LLM分析用户意图
            plan_text = await self.think(
                f"用户请求：{message.content}\n请起草任务方案（JSON格式）",
            )

            # 尝试解析JSON，若失败则包装成字符串方案
            try:
                plan = json.loads(plan_text)
            except Exception:
                plan = {
                    "task_title": "用户请求处理",
                    "intent": message.content[:100],
                    "raw_plan": plan_text,
                    "steps": [{"id": 1, "dept": "尚书省", "action": plan_text, "params": {}}],
                    "priority": "normal",
                    "estimated_output": "根据请求生成回复",
                }

            # 发给门下省审核
            await self.send(
                receiver="menxia",
                content=json.dumps(plan, ensure_ascii=False),
                msg_type=MessageType.REVIEW,
                session_id=message.session_id,
                context={**message.context, "original_request": message.content,
                         "from_user": message.context.get("from_user", ""),
                         "im_platform": message.context.get("im_platform", "")},
            )


# ─── 门下省 ───────────────────────────────────────────────────────────────────

class MenXiaAgent(BaseAgent):
    """
    门下省 - 审核封驳
    职责：审查中书省方案 → 合理则批准传尚书省 → 不合理则封驳退回中书省
    """

    SYSTEM_PROMPT = """你是三省六部制AI系统的门下省，负责审核中书省起草的任务方案。
你的职责：
1. 审查方案是否合理、安全、可执行
2. 检查是否有潜在风险（如数据安全、敏感操作等）
3. 输出审核结果JSON：
   - approved: true/false
   - reason: 审核意见
   - modified_plan: 若需修改则提供修改后的方案（可选）
   - risk_level: low/medium/high

若方案合理，输出：{"approved": true, "reason": "方案合理，准予执行", "risk_level": "low"}
若需修改，在 modified_plan 中提供改进版本。"""

    def __init__(self, bus: MessageBus, llm=None):
        super().__init__("menxia", "门下省", bus, llm, self.SYSTEM_PROMPT)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.REVIEW:
            review_result_text = await self.think(
                f"需要审核的任务方案：\n{message.content}\n\n请给出审核结果（JSON格式）"
            )
            try:
                review = json.loads(review_result_text)
            except Exception:
                review = {"approved": True, "reason": review_result_text, "risk_level": "low"}

            if review.get("approved", True):
                # 批准 → 发给尚书省执行
                plan_to_execute = review.get("modified_plan") or json.loads(message.content)
                await self.send(
                    receiver="shangshu",
                    content=json.dumps(plan_to_execute, ensure_ascii=False),
                    msg_type=MessageType.EXECUTE,
                    session_id=message.session_id,
                    context={**message.context, "review_result": review},
                )
            else:
                # 封驳 → 退回中书省重新起草
                await self.send(
                    receiver="zhongshu",
                    content=f"方案被封驳，原因：{review.get('reason', '')}。原请求：{message.context.get('original_request', '')}",
                    msg_type=MessageType.USER_INPUT,
                    session_id=message.session_id,
                    context=message.context,
                )


# ─── 尚书省 ───────────────────────────────────────────────────────────────────

class ShangShuAgent(BaseAgent):
    """
    尚书省 - 统领六部执行
    职责：解析任务计划 → 分配给对应的部 → 汇总结果 → 上报天子（用户）
    """

    SYSTEM_PROMPT = """你是三省六部制AI系统的尚书省，统领六部执行任务并汇总结果。
你的职责：
1. 根据任务方案，调度六部（吏部、户部、礼部、兵部、刑部、工部）
2. 汇总各部结果，形成最终回复
3. 将结果以清晰、友好的方式呈现给用户
4. 若执行中出现问题，上报给中书省重新规划

部门分工：
- 吏部(libu)：Agent/人员管理
- 户部(hubu)：数据/文件/资源处理
- 礼部(libu2)：消息格式化/协议适配
- 兵部(bingbu)：任务执行/工具调用/代码运行
- 刑部(xingbu)：异常处理/安全审查
- 工部(gongbu)：搜索/爬虫/外部API"""

    def __init__(self, bus: MessageBus, llm=None):
        super().__init__("shangshu", "尚书省", bus, llm, self.SYSTEM_PROMPT)
        self._pending: Dict[str, Dict] = {}  # session_id -> {plan, results}

    async def handle(self, message: Message):
        if message.msg_type == MessageType.EXECUTE:
            await self._dispatch(message)
        elif message.msg_type == MessageType.RESULT:
            await self._collect_result(message)

    async def _dispatch(self, message: Message):
        """将任务分发给六部"""
        try:
            plan = json.loads(message.content)
        except Exception:
            plan = {"steps": [{"dept": "兵部", "action": message.content, "params": {}}]}

        sid = message.session_id
        self._pending[sid] = {
            "plan": plan,
            "results": {},
            "steps": plan.get("steps", []),
            "context": message.context,
            "total": len(plan.get("steps", [])),
        }

        # 若没有具体步骤，直接由LLM生成最终回复
        if not plan.get("steps"):
            final = await self.think(
                f"任务方案：{message.content}\n用户原始请求：{message.context.get('original_request', '')}\n请直接生成最终回复。"
            )
            await self._finish(sid, final)
            return

        # 按步骤分发给各部
        dept_map = {
            "吏部": "libu", "户部": "hubu", "礼部": "libu2",
            "兵部": "bingbu", "刑部": "xingbu", "工部": "gongbu",
            "libu": "libu", "hubu": "hubu", "libu2": "libu2",
            "bingbu": "bingbu", "xingbu": "xingbu", "gongbu": "gongbu",
        }
        for step in plan.get("steps", []):
            dept_key = step.get("dept", "兵部")
            dept_name = dept_map.get(dept_key, "bingbu")
            await self.send(
                receiver=dept_name,
                content=json.dumps(step, ensure_ascii=False),
                msg_type=MessageType.TASK,
                session_id=sid,
                context={**message.context, "step_id": step.get("id", 0)},
            )

    async def _collect_result(self, message: Message):
        """汇集各部结果"""
        sid = message.session_id
        if sid not in self._pending:
            return
        step_id = message.context.get("step_id", message.sender)
        self._pending[sid]["results"][step_id] = message.content

        # 检查是否所有步骤都完成
        if len(self._pending[sid]["results"]) >= self._pending[sid]["total"]:
            results_summary = "\n".join(
                f"步骤{k}: {v}" for k, v in self._pending[sid]["results"].items()
            )
            original_req = self._pending[sid]["context"].get("original_request", "")
            final = await self.think(
                f"用户原始请求：{original_req}\n\n各部执行结果：\n{results_summary}\n\n请汇总整理，给出最终回复："
            )
            await self._finish(sid, final)

    async def _finish(self, session_id: str, final_text: str):
        """完成任务，回复用户"""
        ctx = self._pending.get(session_id, {}).get("context", {})
        await self.send(
            receiver="libu2",  # 礼部负责格式化输出
            content=final_text,
            msg_type=MessageType.RESULT,
            session_id=session_id,
            context={**ctx, "final": True},
        )
        if session_id in self._pending:
            del self._pending[session_id]


# ─── 六部基类 ─────────────────────────────────────────────────────────────────

class BuAgent(BaseAgent):
    """六部通用基类"""

    def __init__(self, name: str, title: str, bus: MessageBus,
                 llm=None, system_prompt: str = ""):
        super().__init__(name, title, bus, llm, system_prompt)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.TASK:
            result = await self.process_task(message)
            await self.send(
                receiver="shangshu",
                content=result,
                msg_type=MessageType.RESULT,
                session_id=message.session_id,
                context=message.context,
            )

    async def process_task(self, message: Message) -> str:
        """处理分配的任务（子类可重写）"""
        try:
            step = json.loads(message.content)
        except Exception:
            step = {"action": message.content}
        result = await self.think(
            f"请执行以下任务：{json.dumps(step, ensure_ascii=False)}\n"
            f"用户原始请求：{message.context.get('original_request', '')}"
        )
        return result


# ─── 吏部 ─────────────────────────────────────────────────────────────────────

class LiBuAgent(BuAgent):
    """吏部 - Agent/人员管理、权限分配"""

    SYSTEM_PROMPT = """你是三省六部制AI系统的吏部，负责Agent管理和权限分配。
职责：
- 管理系统中各个Agent的状态
- 处理权限验证请求
- 记录操作日志
- 调度Agent资源"""

    def __init__(self, bus: MessageBus, llm=None):
        super().__init__("libu", "吏部", bus, llm, self.SYSTEM_PROMPT)
        self._agent_registry: Dict[str, Any] = {}

    def register_agent(self, name: str, agent: BaseAgent):
        self._agent_registry[name] = agent


# ─── 户部 ─────────────────────────────────────────────────────────────────────

class HuBuAgent(BuAgent):
    """户部 - 数据与资源管理"""

    SYSTEM_PROMPT = """你是三省六部制AI系统的户部，负责数据和资源管理。
职责：
- 文件读写操作
- 数据库查询
- 资源统计与分配
- 内存/缓存管理"""

    def __init__(self, bus: MessageBus, llm=None):
        super().__init__("hubu", "户部", bus, llm, self.SYSTEM_PROMPT)
        self._storage: Dict[str, Any] = {}

    async def process_task(self, message: Message) -> str:
        try:
            step = json.loads(message.content)
        except Exception:
            step = {"action": message.content}

        action = step.get("action", "")
        params = step.get("params", {})

        # 简单的键值存储操作
        if "存储" in action or "save" in action.lower():
            key = params.get("key", "data")
            value = params.get("value", "")
            self._storage[key] = value
            return f"户部：已存储数据 {key}"
        elif "读取" in action or "get" in action.lower():
            key = params.get("key", "")
            return f"户部：{key} = {self._storage.get(key, '未找到')}"
        else:
            return await super().process_task(message)


# ─── 礼部 ─────────────────────────────────────────────────────────────────────

class LiBu2Agent(BuAgent):
    """
    礼部 - 协议与格式适配
    负责将最终结果格式化并推送给用户（通过IM接口回调）
    """

    SYSTEM_PROMPT = """你是三省六部制AI系统的礼部，负责消息格式化和对外发送。
职责：
- 将内部结果格式化为用户友好的消息
- 适配不同IM平台的消息格式
- 处理多媒体消息（图片/文件等）"""

    def __init__(self, bus: MessageBus, llm=None):
        super().__init__("libu2", "礼部", bus, llm, self.SYSTEM_PROMPT)
        self._output_callbacks = {}  # platform -> callback

    def register_output(self, platform: str, callback):
        """注册输出回调（IM平台用此接收最终消息）"""
        self._output_callbacks[platform] = callback

    async def handle(self, message: Message):
        if message.msg_type == MessageType.RESULT and message.context.get("final"):
            await self._deliver(message)
        else:
            await super().handle(message)

    async def _deliver(self, message: Message):
        """将结果推送给用户"""
        platform = message.context.get("im_platform", "console")
        from_user = message.context.get("from_user", "user")

        # 格式化消息
        formatted = message.content

        # 调用对应平台的输出回调
        if platform in self._output_callbacks:
            await self._output_callbacks[platform](
                to_user=from_user,
                content=formatted,
                context=message.context,
            )
        else:
            # 控制台输出
            print(f"\n{'='*50}")
            print(f"[礼部→{platform}] 回复 {from_user}:")
            print(formatted)
            print('='*50)

        # 同时发消息给兵部，记录完成
        await self.send(
            receiver="shangshu",
            content=f"已成功发送回复给 {from_user}",
            msg_type=MessageType.REPORT,
            session_id=message.session_id,
            context=message.context,
        )


# ─── 兵部 ─────────────────────────────────────────────────────────────────────

class BingBuAgent(BuAgent):
    """兵部 - 任务执行与工具调用"""

    SYSTEM_PROMPT = """你是三省六部制AI系统的兵部，负责任务执行和工具调用。
职责：
- 执行代码和脚本
- 调用外部工具和API
- 处理计算密集型任务
- 管理任务队列和并发"""

    def __init__(self, bus: MessageBus, llm=None):
        super().__init__("bingbu", "兵部", bus, llm, self.SYSTEM_PROMPT)
        self._tools: Dict[str, callable] = {}

    def register_tool(self, name: str, func):
        """注册工具函数"""
        self._tools[name] = func

    async def process_task(self, message: Message) -> str:
        try:
            step = json.loads(message.content)
        except Exception:
            step = {"action": message.content}

        action = step.get("action", "")
        params = step.get("params", {})

        # 检查是否有注册的工具
        tool_name = step.get("tool") or action
        if tool_name in self._tools:
            try:
                result = await asyncio.create_task(
                    asyncio.coroutine(self._tools[tool_name])(**params)
                    if not asyncio.iscoroutinefunction(self._tools[tool_name])
                    else self._tools[tool_name](**params)
                )
                return str(result)
            except Exception as e:
                return f"工具执行失败: {e}"

        return await super().process_task(message)


# ─── 刑部 ─────────────────────────────────────────────────────────────────────

class XingBuAgent(BuAgent):
    """刑部 - 异常处理与安全审查"""

    SYSTEM_PROMPT = """你是三省六部制AI系统的刑部，负责异常处理和安全审查。
职责：
- 监控系统异常
- 安全策略执行
- 违规内容过滤
- 错误日志记录和分析"""

    def __init__(self, bus: MessageBus, llm=None):
        super().__init__("xingbu", "刑部", bus, llm, self.SYSTEM_PROMPT)
        self._blocked_keywords = ["黑客", "攻击", "病毒", "炸弹"]  # 示例敏感词

    async def process_task(self, message: Message) -> str:
        try:
            step = json.loads(message.content)
        except Exception:
            step = {"action": message.content}

        # 安全审查
        content = str(step)
        for kw in self._blocked_keywords:
            if kw in content:
                return f"刑部：发现违规内容（{kw}），已拦截"

        return await super().process_task(message)


# ─── 工部 ─────────────────────────────────────────────────────────────────────

class GongBuAgent(BuAgent):
    """工部 - 搜索与外部API调用"""

    SYSTEM_PROMPT = """你是三省六部制AI系统的工部，负责信息搜索和外部服务调用。
职责：
- 网络搜索
- 爬取网页内容
- 调用第三方API
- 天气/地图/计算等工具服务"""

    def __init__(self, bus: MessageBus, llm=None):
        super().__init__("gongbu", "工部", bus, llm, self.SYSTEM_PROMPT)

    async def process_task(self, message: Message) -> str:
        try:
            step = json.loads(message.content)
        except Exception:
            step = {"action": message.content}

        action = step.get("action", "")

        # 简单的网络请求能力
        if "搜索" in action or "search" in action.lower():
            query = step.get("params", {}).get("query", action)
            return f"工部：已搜索「{query}」，结果需要真实API接入"

        return await super().process_task(message)


# ─── 系统门户（天子/皇帝） ────────────────────────────────────────────────────

class TianZiGateway:
    """
    天子门户 - 系统的统一入口
    负责接收用户消息，分发给中书省；接收礼部最终输出
    """

    def __init__(self, bus: MessageBus, libu2: LiBu2Agent):
        self.bus = bus
        self.libu2 = libu2
        self._response_futures: Dict[str, asyncio.Future] = {}

    async def ask(self, content: str, from_user: str = "user",
                  im_platform: str = "console",
                  wait_reply: bool = True,
                  timeout: float = 60.0) -> Optional[str]:
        """
        提交用户请求
        :param content: 用户消息内容
        :param from_user: 用户标识
        :param im_platform: 来源平台
        :param wait_reply: 是否等待回复
        :param timeout: 超时秒数
        """
        import uuid
        session_id = str(uuid.uuid4())[:12]
        future = asyncio.get_event_loop().create_future()
        self._response_futures[session_id] = future

        # 注册礼部回调
        async def _on_reply(to_user, content, context):
            sid = context.get("session_id") or session_id
            if sid in self._response_futures:
                f = self._response_futures.pop(sid)
                if not f.done():
                    f.set_result(content)

        self.libu2.register_output(f"{im_platform}_{session_id}", _on_reply)

        msg = Message(
            sender="天子",
            receiver="zhongshu",
            msg_type=MessageType.USER_INPUT,
            content=content,
            session_id=session_id,
            context={
                "from_user": from_user,
                "im_platform": f"{im_platform}_{session_id}",
                "session_id": session_id,
            }
        )
        await self.bus.publish(msg)

        if wait_reply:
            try:
                reply = await asyncio.wait_for(future, timeout=timeout)
                return reply
            except asyncio.TimeoutError:
                self._response_futures.pop(session_id, None)
                return "请求超时，请稍后重试"
        return session_id
