# 三省六部制 Multi-Agent 框架

> 🏛️ 以中国古代**三省六部制**为架构的多Agent系统，支持任意LLM后端，可通过微信、飞书等IM软件交互。

---

## 🏗️ 系统架构

```
用户输入（微信/飞书/钉钉/Web）
        │
        ▼
  ┌─────────────┐
  │  中书省     │  草拟诏令：分析用户意图，生成结构化任务方案
  └──────┬──────┘
         │ 审核
         ▼
  ┌─────────────┐
  │  门下省     │  审核封驳：把关质量，可封驳退回重拟
  └──────┬──────┘
         │ 批准
         ▼
  ┌─────────────┐         ┌──────┐ ┌──────┐ ┌──────┐
  │  尚书省     │ ──调度──▶│ 吏部 │ │ 户部 │ │ 礼部 │
  └─────────────┘         └──────┘ └──────┘ └──────┘
                          ┌──────┐ ┌──────┐ ┌──────┐
                          │ 兵部 │ │ 刑部 │ │ 工部 │
                          └──────┘ └──────┘ └──────┘
                                              │
                                              ▼
                                    礼部格式化 → 回复用户
```

### 三省职责

| 官署 | 职责 | 对应功能 |
|------|------|----------|
| **中书省** | 草拟诏令 | 解析用户意图、生成任务规划 |
| **门下省** | 审核封驳 | 质量把关、风险审查 |
| **尚书省** | 统领六部 | 任务调度、结果汇总 |

### 六部职责

| 官署 | 职责 | 对应功能 |
|------|------|----------|
| **吏部** | 人员管理 | Agent注册、权限控制 |
| **户部** | 资源管理 | 数据存储、文件操作 |
| **礼部** | 礼仪外交 | 消息格式化、IM平台适配 |
| **兵部** | 军事执行 | 工具调用、代码运行 |
| **刑部** | 司法安全 | 异常处理、内容安全审查 |
| **工部** | 基础建设 | 网络搜索、外部API调用 |

---

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 方式一：Web 控制台（推荐）

```bash
# 使用 Mock LLM 测试
python main.py

# 使用 OpenAI
LLM_PROVIDER=openai LLM_API_KEY=sk-xxx LLM_MODEL=gpt-4o python main.py

# 使用通义千问
LLM_PROVIDER=qwen LLM_API_KEY=xxx LLM_MODEL=qwen-max python main.py

# 使用本地 Ollama
LLM_PROVIDER=ollama LLM_MODEL=qwen2 python main.py
```

浏览器访问 http://localhost:8000

### 方式二：Python 代码调用

```python
import asyncio
from core.system import create_system

async def main():
    # 创建系统
    system = await create_system("openai", api_key="sk-...", model="gpt-4o")

    # 直接问答
    reply = await system.ask("帮我分析一下当前AI行业的发展趋势")
    print(reply)

    # 注册自定义工具（给兵部）
    async def search_web(query: str) -> str:
        # 接入真实搜索API
        return f"搜索结果: {query}"

    system.register_tool("search", search_web)

    # 运行时切换LLM
    from core.llm import create_llm
    new_llm = create_llm("qwen", api_key="...", model="qwen-max")
    system.switch_llm(new_llm)

    await system.stop()

asyncio.run(main())
```

### 方式三：运行示例

```bash
python examples.py
```

---

## 📱 IM 接入配置

### 飞书机器人

1. 在[飞书开发者控制台](https://open.feishu.cn/app)创建应用
2. 开启「接收消息」事件，订阅 URL 填 `https://你的域名/feishu`
3. 配置环境变量：
   ```bash
   FEISHU_ENABLED=true
   FEISHU_APP_ID=cli_xxx
   FEISHU_APP_SECRET=xxx
   FEISHU_VERIFY_TOKEN=xxx
   ```

### 微信公众号

1. 在[微信公众平台](https://mp.weixin.qq.com/)配置服务器
2. 服务器URL填 `https://你的域名/wechat`
3. 配置环境变量：
   ```bash
   WECHAT_OA_ENABLED=true
   WECHAT_APP_ID=wxXXX
   WECHAT_APP_SECRET=xxx
   WECHAT_TOKEN=你设置的Token
   ```

### 微信个人号（gewechat）

```python
from im.adapters import WeChatAdapter

wechat = WeChatAdapter(
    system,
    mode="gewechat",
    gewechat_base_url="http://localhost:2531",
    gewechat_token="你的token",
)
await wechat.start()
```

### 钉钉

```bash
DINGTALK_ENABLED=true
DINGTALK_APP_KEY=xxx
DINGTALK_APP_SECRET=xxx
```

---

## 🤖 支持的 LLM

| 提供商 | provider 值 | 备注 |
|--------|------------|------|
| OpenAI | `openai` | GPT-4o, GPT-4, GPT-3.5等 |
| Azure OpenAI | `azure` | 需配置 base_url |
| Anthropic | `claude` | Claude 3.5/3等 |
| 阿里通义千问 | `qwen` | qwen-max, qwen-plus等 |
| 百度文心一言 | `wenxin` | 需额外配置 secret_key |
| Google Gemini | `gemini` | gemini-1.5-pro等 |
| Ollama本地 | `ollama` | llama3, qwen2, mistral等 |
| Mock测试 | `mock` | 无需API，用于测试 |

---

## 📁 项目结构

```
sangsheng-liubu/
├── main.py                    # 主启动入口
├── examples.py                # 使用示例
├── requirements.txt           # 依赖
├── .env.example               # 环境变量模板
│
├── core/
│   ├── base.py                # Agent基类、消息总线、消息体
│   ├── llm.py                 # LLM适配器（OpenAI/Claude/文心/通义等）
│   └── system.py              # 系统工厂、入口
│
├── agents/
│   └── sansheng_liubu.py      # 三省六部 Agent 实现
│
├── im/
│   └── adapters.py            # IM适配器（微信/飞书/钉钉/Telegram）
│
└── web/
    ├── api.py                 # FastAPI 路由
    └── templates/
        └── index.html         # Web控制台前端
```

---

## 🔧 扩展开发

### 添加新的 Agent

```python
from core.base import BaseAgent, Message, MessageType

class MyCustomAgent(BaseAgent):
    def __init__(self, bus, llm=None):
        super().__init__("my_agent", "自定义官署", bus, llm,
                         system_prompt="你的Agent职责描述...")

    async def handle(self, message: Message):
        if message.msg_type == MessageType.TASK:
            result = await self.think(f"处理任务: {message.content}")
            await self.send("shangshu", result, MessageType.RESULT,
                           session_id=message.session_id,
                           context=message.context)
```

### 注册工具给兵部

```python
async def my_tool(param1: str, param2: int) -> str:
    # 工具逻辑
    return "工具执行结果"

system.register_tool("my_tool", my_tool)
```

### 自定义LLM

```python
from core.llm import BaseLLM

class MyLLM(BaseLLM):
    async def chat(self, messages, **kwargs) -> str:
        # 调用自定义API
        return "回复"

    async def stream_chat(self, messages, **kwargs):
        yield "流式回复"
```

---

## License

MIT
