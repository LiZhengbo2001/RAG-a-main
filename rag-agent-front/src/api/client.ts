import type {
  ChatRequest,
  ChatResponse,
  StreamEvent,
  Conversation,
  KnowledgeDoc,
} from '../types';

const BASE = '/api';

// ── helpers ──
function getToken(): string | null {
  return localStorage.getItem('rag_agent_token');
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> || {}),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers,
  });
  if (res.status === 401) {
    localStorage.removeItem('rag_agent_token');
    throw new Error('登录已过期，请重新登录');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? `请求失败 (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// ── Chat ──

export async function sendChat(req: ChatRequest): Promise<ChatResponse> {
  return request<ChatResponse>('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

export async function streamChat(
  req: ChatRequest,
  onEvent: (e: StreamEvent) => void,
  onError: (err: Error) => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const token = getToken();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch(`${BASE}/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify(req),
      signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail ?? `流式请求失败 (${res.status})`);
    }

    const reader = res.body?.getReader();
    if (!reader) throw new Error('响应体不可读');

    const decoder = new TextDecoder();
    let buffer = '';
    let eventType = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        const t = line.trim();
        if (t.startsWith('event:')) { eventType = t.slice(6).trim(); continue; }
        if (!t.startsWith('data:')) continue;
        const raw = t.slice(5).trim();
        if (!raw) continue;

        let parsed: any;
        try { parsed = JSON.parse(raw); } catch { onEvent({ type: 'token', text: raw }); continue; }

        switch (eventType) {
          case 'thinking': onEvent({ type: 'thinking', step: { type: parsed.type, text: parsed.text ?? parsed.step } }); break;
          case 'token':    onEvent({ type: 'token',    text: parsed.text ?? '' }); break;
          case 'sources':  onEvent({ type: 'sources',  sources: Array.isArray(parsed) ? parsed : [] }); break;
          case 'trace':    onEvent({ type: 'trace',    steps: Array.isArray(parsed) ? parsed : [] }); break;
          case 'done':     onEvent({ type: 'done',     conversation_id: parsed.conversation_id ?? '' }); break;
          case 'error':    onEvent({ type: 'error',    message: parsed.message ?? '未知错误' }); break;
          default:
            if (parsed.text !== undefined) onEvent({ type: 'token', text: parsed.text });
        }
        eventType = '';
      }
    }
  } catch (err: any) {
    if (err.name === 'AbortError') return;
    onError(err instanceof Error ? err : new Error(String(err)));
  }
}

// ── Conversations ──

export function listConversations(): Promise<Conversation[]> {
  return request<Conversation[]>('/conversations');
}

export function createConversation(title: string): Promise<Conversation> {
  return request<Conversation>('/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
}

export function deleteConversation(id: string): Promise<void> {
  return request<void>(`/conversations/${id}`, { method: 'DELETE' });
}

export function getConversation(id: string): Promise<{ messages: any[] }> {
  return request(`/conversations/${id}`);
}

// ── Documents (Knowledge Base) ──

export function listDocuments(): Promise<KnowledgeDoc[]> {
  return request<KnowledgeDoc[]>('/documents');
}

export function uploadDocument(file: File): Promise<KnowledgeDoc> {
  const form = new FormData();
  form.append('file', file);
  return request<KnowledgeDoc>('/documents/upload', {
    method: 'POST',
    body: form,
  });
}

export function deleteDocument(id: string): Promise<void> {
  return request<void>(`/documents/${id}`, { method: 'DELETE' });
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
}

export interface UserInfo {
  id: string;
  username: string;
}

export function register(username: string, password: string): Promise<AuthResponse> {
  return request<AuthResponse>('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
}

export function login(username: string, password: string): Promise<AuthResponse> {
  return request<AuthResponse>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
}

export function getMe(): Promise<UserInfo> {
  return request<UserInfo>('/auth/me');
}