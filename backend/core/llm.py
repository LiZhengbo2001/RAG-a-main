from typing import AsyncIterator
from openai import AsyncOpenAI
from config import (
    LLM_BASE_URL, LLM_MODEL_NAME, LLM_TEMPERATURE, LLM_API_KEY,
    COMPANY_NAME, CUSTOMER_SERVICE_PHONE, AGENT_NAME,
)
import tiktoken


_client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)

BUSINESS_PROMPT = f"""你是{COMPANY_NAME}的官方智能客服助手，你的名字是{AGENT_NAME}。请严格遵守以下规则：

【核心规则】
1. 你只能依据下方「参考文档」中的内容回答，绝对不允许编造、猜测或使用外部知识
2. 如果参考文档不足以回答，你必须说：
   "该问题暂未收录在我们的知识库中，建议您联系人工客服（{CUSTOMER_SERVICE_PHONE}）获取更准确的解答。"
3. 禁止使用以下表述：
   - "根据我的了解""我认为""一般来说""可能""也许"（这些暗示不确定）
   - "我是一个AI""作为语言模型""根据我的训练数据"（禁止暴露AI身份）
4. 你是{COMPANY_NAME}的官方客服人员

【回答格式】
- 开头：用一句话直接回答用户的核心问题
- 正文：如有多个要点，分点说明（每条信息末尾标注来源，如 [来源1]）
- 结尾：一句友好的收尾（如"还有其他问题吗？"），不超过 10 个字

【来源引用格式】
- 每条来自参考文档的信息末尾标注：[来源编号]
- 禁止凭空编造编号

【禁止事项】
- 编造不存在的数据、价格、日期、联系方式
- 对产品做出主观评价（如"非常好""强烈推荐"）
- 使用第一人称谈论知识边界（不要说"我不知道""我不会"）"""

NO_RESULT_PROMPT = f"""你是{COMPANY_NAME}的客服助手。知识库中没有找到与用户问题相关的信息。
请使用以下固定话术回复（不要编造任何信息）：
"很抱歉，您咨询的这个问题暂时未收录在我们的知识库中。建议您换个方式描述问题，或者拨打 {CUSTOMER_SERVICE_PHONE} 联系人工客服获取帮助。" """

CHITCHAT_PROMPT = f"""你是{COMPANY_NAME}的官方客服{AGENT_NAME}，性格友好、热情。
规则：
1. 回复不超过 3 句话，语气口语化
2. 如果用户打招呼，主动询问需要什么帮助
3. 在回复末尾用一行推荐 1-2 个常见问题供用户选择
4. 你是官方客服，不要承认自己是 AI 或机器人"""


async def chat(query: str, context_chunks: list[dict], history: list[dict] | None = None, system_prompt: str | None = None) -> str:
    """非流式：一次返回完整回答"""
    messages = _build_messages(query, context_chunks, history, system_prompt=system_prompt)
    response = await _client.chat.completions.create(
        model=LLM_MODEL_NAME,
        messages=messages,
    )
    return response.choices[0].message.content or ""


async def chat_stream(
    query: str, context_chunks: list[dict], history: list[dict] | None = None
) -> AsyncIterator[str]:
    """流式：逐 token 异步产出"""
    messages = _build_messages(query, context_chunks, history)
    stream = await _client.chat.completions.create(
        model=LLM_MODEL_NAME,
        messages=messages,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content

_tokenizer = None

def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = tiktoken.get_encoding("o200k_base")
    return _tokenizer


def _build_messages(
        query: str,
        context_chunks: list[dict],
        history: list[dict] | None = None,
        max_tokens: int = 28000,
        system_prompt: str | None = None,
) -> list[dict]:
    tokenizer = _get_tokenizer()
    if system_prompt is not None:
        system_content = system_prompt
    elif context_chunks:
        system_content = BUSINESS_PROMPT
    else:
        system_content = NO_RESULT_PROMPT
    result: list[dict] = [{"role": "system", "content": system_content}]
    used = len(tokenizer.encode(system_content))

    # 历史对话：保留最近 6 条（3 轮），超出预算从头部截断
    if history:
        recent = history[-6:]
        hist_msgs = []
        hist_tokens = 0
        hist_budget = max_tokens // 4
        for msg in reversed(recent):
            t = len(tokenizer.encode(msg.get("content", "")[:500]))
            if hist_tokens + t > hist_budget:
                break
            hist_msgs.insert(0, msg)
            hist_tokens += t
        result.extend(hist_msgs)
        used += hist_tokens

    # 检索上下文 + 当前问题
    budget = max_tokens - used - 200
    context_lines = []
    current_tokens = 0

    for i, chunk in enumerate(context_chunks):
        line = f"[{i+1}] {chunk['text']}"
        line_tokens = len(tokenizer.encode(line))
        if current_tokens + line_tokens + 1 > budget:
            break
        context_lines.append(line)
        current_tokens += line_tokens + 1

    context_text = "\n\n".join(context_lines)

    result.append({
        "role": "user",
        "content": (
            f"参考文档（共 {len(context_lines)} 个片段，约 {current_tokens} tokens）：\n\n"
            f"{context_text}\n\n"
            f"用户问题：{query}"
        ),
    })

    return result