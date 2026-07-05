// ── Message types ──

export interface Source {
  id: number;
  title: string;
  author?: string;
  year?: number;
  score: number;
  rerank_score?: number;
  excerpt?: string;
  url?: string;
}

export interface ThinkingStep {
  type: 'search' | 'result' | 'generate';
  text: string;
}

export interface TraceStep {
  phase: 'planning' | 'retrieval' | 'generation';
  label: string;
  detail: string;
  time: string;
}

export interface UserMessage {
  id: string;
  role: 'user';
  content: string;
  timestamp: string;
}

export interface AgentMessage {
  id: string;
  role: 'agent';
  content: string;
  timestamp: string;
  thinking: ThinkingStep[] | null;
  sources: Source[] | null;
  trace: TraceStep[] | null;
}

export type Message = UserMessage | AgentMessage;

// ── Conversations ──

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

// ── Documents ──

export type DocumentStatus = 'processing' | 'ready' | 'error';

export interface KnowledgeDoc {
  id: string;
  filename: string;
  size: number;
  status: DocumentStatus;
  created_at: string;
  chunk_count?: number;
}

// ── API ──

export interface ChatRequest {
  query: string;
  conversation_id?: string;
  image?: string;
}

export interface ChatResponse {
  answer: string;
  thinking: ThinkingStep[];
  sources: Source[];
  trace: TraceStep[];
  conversation_id: string;
}

// ── Streaming events ──

export type StreamEvent =
  | { type: 'thinking'; step: ThinkingStep }
  | { type: 'token';    text: string }
  | { type: 'sources';  sources: Source[] }
  | { type: 'trace';    steps: TraceStep[] }
  | { type: 'done';     conversation_id: string }
  | { type: 'error';    message: string };

// ── Navigation ──

export type NavTab = 'chat' | 'knowledge';
