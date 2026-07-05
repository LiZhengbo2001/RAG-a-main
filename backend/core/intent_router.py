"""意图路由：区分业务问题和闲聊，决定走 RAG 还是模板回复"""

from core.llm import chat

_INTENT_PROMPT = """判断以下用户消息的意图类型。
- business：询问产品、服务、价格、政策、技术问题、使用帮助等与业务相关的问题
- chitchat：打招呼、感谢、告别、闲聊、测试等与业务无关的对话
只回复一个词：business 或 chitchat

用户消息：{query}
意图："""

# 快速过滤：短问候类消息不调 LLM，直接判 chitchat
_FAST_CHITCHAT_KEYWORDS = [
    "你好", "您好", "hi", "hello", "嗨", "哈喽",
    "谢谢", "感谢", "多谢", "thanks",
    "再见", "拜拜", "bye", "晚安",
    "测试", "test", "在吗", "有人在吗",
]


def _is_fast_chitchat(query: str) -> bool:
    """短问候消息直接判闲聊，省一次 LLM 调用"""
    q = query.strip().lower()
    if len(q) < 10:
        for kw in _FAST_CHITCHAT_KEYWORDS:
            if kw in q:
                return True
    return False


async def classify(query: str) -> str:
    """返回 "business" 或 "chitchat" """
    if _is_fast_chitchat(query):
        return "chitchat"

    prompt = _INTENT_PROMPT.format(query=query)
    try:
        result = await chat(prompt, [])
        result = result.strip().lower()
        if "chitchat" in result:
            return "chitchat"
        return "business"
    except Exception:
        # LLM 调用失败，默认按 business 处理（宁可多检索，不可漏业务）
        return "business"