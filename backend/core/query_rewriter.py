"""查询改写：将口语化问题转为检索友好的关键词 + 短句"""

from core.llm import chat

_REWRITE_PROMPT = """将用户问题改写为更适合搜索引擎的关键词短句。必须改写，绝对不能原样返回。

改写要求：
1. 提取问题中的核心概念，扩展同义词和专业术语
2. 用 5-10 个词组成连续的搜索短语，不要用逗号分隔
3. 如果问题是"什么是XX"，改写为"XX 定义 概念 原理 特点"
4. 只输出改写后的文本，不要加任何前缀、解释或标点

原始问题：什么是RAG
改写：RAG 检索增强生成 定义 原理 工作流程

原始问题：Transformer的QKV公式怎么推导
改写：Transformer 自注意力 QKV 公式 数学推导 缩放点积

原始问题：{query}
改写："""


async def rewrite_query(query: str) -> str:
    prompt = _REWRITE_PROMPT.format(query=query)
    result = await chat(prompt, [], system_prompt="你是一个搜索查询改写助手。请直接输出改写后的文本，不要加任何解释、前缀或后缀。")
    rewritten = result.strip()

    # 去引号和换行
    rewritten = rewritten.strip('"\'').replace('\n', ' ')

    # 如果改写后和原问题一模一样，说明 LLM 偷懒了，手动拼一个
    if rewritten == query:
        return query  # 不做无意义改写

    return rewritten if rewritten else query
