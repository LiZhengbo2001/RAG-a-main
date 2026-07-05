import { useState, useRef, useCallback, useEffect } from 'react';
import type { Message, AgentMessage, ThinkingStep, Source, TraceStep, StreamEvent, Conversation } from '../types';
import { streamChat, listConversations, createConversation, deleteConversation, getConversation } from '../api/client';


let msgCounter = 0;
function nextId(): string { msgCounter += 1; return `msg-${Date.now()}-${msgCounter}`; }
function ts(): string { return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }); }

export interface UseChatReturn {
  messages: Message[];
  isProcessing: boolean;
  error: string | null;
  conversationId: string | null;
  conversations: Conversation[];
  activeSources: Source[] | null;
  activeTrace: TraceStep[] | null;
  send: (query: string, image?: string) => void;
  abort: () => void;
  clear: () => void;
  newConversation: () => void;
  switchConversation: (id: string) => void;
  removeConversation: (id: string) => void;
  loadConversations: () => void;
}

export function useChat(token: string | null): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);

  const abortRef = useRef<AbortController | null>(null);

  const activeSources = deriveActiveSources(messages);
  const activeTrace = deriveActiveTrace(messages);

  const loadConversations = useCallback(async () => {
    if (!token) return;
    try { setConversations(await listConversations()); } catch { /* offline */ }
  }, [token]);

  useEffect(() => { loadConversations(); }, [loadConversations]);

  // 切换用户时清空缓存
  // 退出时清空缓存，登录时恢复上次会话
  useEffect(() => {
    const savedConvId = localStorage.getItem('rag_agent_last_conv');
    if (!token) {
      // 退出登录：清空缓存，但保留 conversationId 以便下次恢复
      if (conversationId && messages.length > 0) {
        localStorage.setItem('rag_agent_last_conv', conversationId);
      }
      setMessages([]);
      setConversationId(null);
      setConversations([]);
      setError(null);
    } else if (savedConvId) {
      // 重新登录：恢复上次的对话
      setConversationId(savedConvId);
    }
  }, [token]);

  const clear = useCallback(() => { setMessages([]); setError(null); setConversationId(null); }, []);

  const abort = useCallback(() => { abortRef.current?.abort(); abortRef.current = null; }, []);

  const newConversation = useCallback(async () => {
    abort();
    setMessages([]);
    setError(null);
    try {
      const c = await createConversation('新对话');
      setConversationId(c.id);
      await loadConversations();
    } catch {
      setConversationId(null);
    }
    setIsProcessing(false);
  }, [abort, loadConversations]);

  const switchConversation = useCallback(async (id: string) => {
    if (isProcessing) return;
    abort();
    setMessages([]);
    setError(null);
    setConversationId(id);
    setIsProcessing(false);
    try {
        const data = await getConversation(id);
        const history: Message[] = data.messages.map((m: any) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            timestamp: m.timestamp,
            thinking: m.role === 'agent' ? (m.thinking ?? null) : undefined,
            sources: m.role === 'agent' ? (m.sources ?? null) : undefined,
            trace: m.role === 'agent' ? (m.trace ?? null) : undefined,
        }));
        // 如果是空数组，filter 后变成空也没关系
        const valid: Message[] = [];
        for (const m of history) {
            if (m.role === 'user') {
                valid.push({ id: m.id, role: 'user', content: m.content, timestamp: m.timestamp });
            } else if (m.role === 'agent') {
                valid.push({
                    id: m.id,
                    role: 'agent',
                    content: m.content,
                    timestamp: m.timestamp,
                    thinking: m.thinking as any,
                    sources: m.sources as any,
                    trace: m.trace as any,
                });
            }
        }
        setMessages(valid);
    } catch {
        // 请求失败则保持空列表，不做额外处理
        setError('请求失败')
    }
}, [isProcessing, abort]);

  const removeConversation = useCallback(async (id: string) => {
    try {
      await deleteConversation(id);
      setConversations(prev => prev.filter(c => c.id !== id));
      if (conversationId === id) {
        setMessages([]);
        setConversationId(null);
      }
    } catch { /* handle error */ }
  }, [conversationId]);

  const send = useCallback((query: string, image?: string) => {
    if ((!query.trim() && !image) || isProcessing) return;
    setError(null);

    const displayContent = image ? `[图片] ${query.trim() || ''}` : query.trim();
    const userMsg: Message = { id: nextId(), role: 'user', content: displayContent, timestamp: ts() };
    const agentId = nextId();
    const agentMsg: AgentMessage = { id: agentId, role: 'agent', content: '', timestamp: ts(), thinking: [], sources: null, trace: null };

    setMessages(prev => [...prev, userMsg, agentMsg]);
    setIsProcessing(true);

    const controller = new AbortController();
    abortRef.current = controller;

    streamChat(
      { query: query.trim(), conversation_id: conversationId ?? undefined, image },
      (event: StreamEvent) => {
        setMessages(prev => prev.map(m => {
          if (m.id !== agentId || m.role !== 'agent') return m;
          const a = { ...m } as AgentMessage;
          switch (event.type) {
            case 'thinking': a.thinking = [...(a.thinking ?? []), event.step]; break;
            case 'token':    a.content += event.text; break;
            case 'sources':  a.sources = event.sources; break;
            case 'trace':    a.trace = event.steps; break;
            case 'done':
              if (event.conversation_id) setConversationId(event.conversation_id);
              break;
            case 'error':    setError(event.message); break;
          }
          return a;
        }));
      },
      (err: Error) => { setError(err.message); setIsProcessing(false); abortRef.current = null; },
      controller.signal,
    ).then(() => {
      setIsProcessing(false);
      abortRef.current = null;
      // Refresh conversation list (title may have updated)
      loadConversations();
    });
  }, [isProcessing, conversationId, loadConversations]);

  return {
    messages, isProcessing, error, conversationId, conversations,
    activeSources, activeTrace,
    send, abort, clear,
    newConversation, switchConversation, removeConversation, loadConversations,
  };
}

function deriveActiveSources(msgs: Message[]): Source[] | null {
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i];
    if (m.role === 'agent' && m.sources) return m.sources;
  }
  return null;
}

function deriveActiveTrace(msgs: Message[]): TraceStep[] | null {
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i];
    if (m.role === 'agent' && m.trace) return m.trace;
  }
  return null;
}
