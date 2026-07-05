import { useState, useCallback, useEffect } from 'react';
import type { KnowledgeDoc } from '../types';
import { listDocuments, uploadDocument, deleteDocument } from '../api/client';

export interface UseKnowledgeReturn {
  documents: KnowledgeDoc[];
  loading: boolean;
  error: string | null;
  upload: (file: File) => Promise<void>;
  remove: (id: string) => Promise<void>;
  refresh: () => void;
}

export function useKnowledge(token: string | null): UseKnowledgeReturn {
  const [documents, setDocuments] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setDocuments(await listDocuments());
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { refresh(); }, [refresh]);

  // 切换用户时清空缓存
  useEffect(() => {
    setDocuments([]);
    setError(null);
  }, [token]);

  const upload = useCallback(async (file: File) => {
    setError(null);
    try {
      const doc = await uploadDocument(file);
      setDocuments(prev => [doc, ...prev]);
    } catch (err: any) {
      setError(err.message);
      throw err;
    }
  }, []);

  const remove = useCallback(async (id: string) => {
    setError(null);
    try {
      await deleteDocument(id);
      setDocuments(prev => prev.filter(d => d.id !== id));
    } catch (err: any) {
      setError(err.message);
    }
  }, []);

  return { documents, loading, error, upload, remove, refresh };
}
