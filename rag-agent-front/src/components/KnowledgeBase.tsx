import { memo, useRef, useState, useCallback } from 'react';
import type { KnowledgeDoc, DocumentStatus } from '../types';

interface KnowledgeBaseProps {
  documents: KnowledgeDoc[];
  loading: boolean;
  error: string | null;
  upload: (file: File) => Promise<void>;
  remove: (id: string) => Promise<void>;
  refresh: () => void;
}

export default memo(function KnowledgeBase({
  documents,
  loading,
  upload,
  remove,
  refresh,
}: KnowledgeBaseProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const handleFile = useCallback(async (file: File) => {
    // 文件大小校验
    if (file.size > 20 * 1024 * 1024) {
      setLocalError('文件过大，最大支持 20MB');
      return;
    }
    setLocalError(null);
    setUploading(true);
    try {
      await upload(file);
    } catch (err: any) {
      setLocalError(err?.message || '上传失败，请稍后重试');
    } finally {
      setUploading(false);
    }
  }, [upload]);

  const handleDelete = useCallback(async (id: string) => {
    setDeleting(id);
    try {
      await remove(id);
    } catch { /* error handled by hook */ }
    finally { setDeleting(null); }
  }, [remove]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const totalSize = documents.reduce((sum, d) => sum + d.size, 0);

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-surface-muted overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 bg-white border-b border-surface-border flex-shrink-0">
        <div>
          <h2 className="text-lg font-semibold text-ink-strong">知识库管理</h2>
          <p className="text-xs text-ink-muted mt-0.5">
            {documents.length} 个文档 · {formatSize(totalSize)}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={refresh}
            disabled={loading}
            className="text-xs text-ink-muted hover:text-ink-body transition-colors disabled:opacity-50"
          >
            {loading ? '刷新中…' : '刷新'}
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="px-4 py-2 bg-primary-500 text-white rounded-xl text-sm font-medium
                       hover:bg-primary-600 active:scale-95 transition-all duration-150
                       disabled:opacity-50 disabled:cursor-not-allowed shadow-sm shadow-primary-200"
          >
            {uploading ? '上传中…' : '上传文档'}
          </button>
        </div>
      </div>

      {/* Upload drop zone */}
      {localError && (
        <div className="mx-6 mt-3 px-4 py-2.5 bg-red-50 border border-red-200 rounded-xl text-xs text-red-600 text-center">
          {localError}
        </div>
      )}
      {uploading && (
        <div className="mx-6 mt-3">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs text-primary-600 font-medium">正在处理文档…</span>
            <span className="text-[11px] text-ink-muted">解析 → 分块 → 向量化</span>
          </div>
          <div className="w-full bg-surface-border rounded-full h-1.5 overflow-hidden">
            <div className="bg-primary-500 h-full rounded-full animate-pulse" style={{ width: '60%' }} />
          </div>
          <p className="text-[11px] text-ink-dim mt-1.5">大文件可能需要 10-30 秒，请耐心等待</p>
        </div>
      )}
      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={() => setDragOver(false)}
        className={`mx-6 mt-4 border-2 border-dashed rounded-2xl p-8 text-center transition-all duration-200
          ${dragOver
            ? 'border-primary-400 bg-primary-50'
            : 'border-surface-border hover:border-primary-200 hover:bg-surface-hover'
          }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept=".pdf,.txt,.md,.doc,.docx,.csv,.json,.html"
          onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ''; }}
        />
        <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-primary-50 flex items-center justify-center">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            className="text-primary-500" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </div>
        <p className="text-sm text-ink-body font-medium">
          拖拽文件到此处，或点击上方「上传文档」按钮
        </p>
        <p className="text-xs text-ink-muted mt-1">
          支持 PDF、TXT、Markdown、Word、CSV、JSON、HTML
        </p>
      </div>

      {/* Document list */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-6 py-4">
        {documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-ink-muted gap-2">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              className="opacity-20" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            <p className="text-sm">知识库为空，上传第一个文档开始构建知识库</p>
          </div>
        ) : (
          <div className="bg-white rounded-2xl border border-surface-border overflow-hidden shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border bg-surface-muted">
                  <th className="text-left px-5 py-3 text-xs font-semibold text-ink-muted uppercase tracking-wider">文件名</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-ink-muted uppercase tracking-wider">大小</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-ink-muted uppercase tracking-wider">状态</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-ink-muted uppercase tracking-wider">上传时间</th>
                  <th className="w-16 px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border">
                {documents.map(doc => (
                  <tr key={doc.id} className="hover:bg-surface-muted/50 transition-colors">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-3">
                        <FileIcon filename={doc.filename} />
                        <span className="text-ink-strong font-medium truncate max-w-[280px] block">
                          {doc.filename}
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-ink-muted font-mono text-xs">
                      {formatSize(doc.size)}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={doc.status} chunks={doc.chunk_count} />
                    </td>
                    <td className="px-5 py-3.5 text-ink-muted text-xs">
                      {formatDateTime(doc.created_at)}
                    </td>
                    <td className="px-5 py-3.5">
                      <button
                        onClick={() => handleDelete(doc.id)}
                        disabled={deleting === doc.id}
                        className="w-7 h-7 rounded-lg flex items-center justify-center
                                   text-ink-dim hover:text-red-500 hover:bg-red-50
                                   transition-all duration-150 disabled:opacity-50"
                        title="删除文档"
                      >
                        {deleting === doc.id ? (
                          <svg className="animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none"
                            stroke="currentColor" strokeWidth="2">
                            <circle cx="12" cy="12" r="10" strokeOpacity="0.2" />
                            <path d="M12 2a10 10 0 019.95 9" />
                          </svg>
                        ) : (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="3 6 5 6 21 6" />
                            <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                          </svg>
                        )}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
});

// ── sub-components ──

function FileIcon({ filename }: { filename: string }) {
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  const icons: Record<string, { bg: string; text: string; label: string }> = {
    pdf:  { bg: 'bg-red-50', text: 'text-red-500', label: 'PDF' },
    txt:  { bg: 'bg-slate-100', text: 'text-slate-500', label: 'TXT' },
    md:   { bg: 'bg-blue-50', text: 'text-blue-500', label: 'MD' },
    doc:  { bg: 'bg-blue-50', text: 'text-blue-500', label: 'DOC' },
    docx: { bg: 'bg-blue-50', text: 'text-blue-500', label: 'DOC' },
    csv:  { bg: 'bg-emerald-50', text: 'text-emerald-500', label: 'CSV' },
    json: { bg: 'bg-amber-50', text: 'text-amber-500', label: 'JSON' },
    html: { bg: 'bg-orange-50', text: 'text-orange-500', label: 'HTML' },
  };
  const style = icons[ext] ?? { bg: 'bg-surface-raised', text: 'text-ink-muted', label: ext.toUpperCase() };

  return (
    <span className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-[10px] font-mono font-semibold ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

function StatusBadge({ status, chunks }: { status: DocumentStatus; chunks?: number }) {
  const map: Record<DocumentStatus, { bg: string; text: string; label: string }> = {
    processing: { bg: 'bg-amber-50', text: 'text-amber-600', label: '处理中…' },
    ready:      { bg: 'bg-emerald-50', text: 'text-emerald-600', label: '就绪' },
    error:      { bg: 'bg-red-50', text: 'text-red-600', label: '失败' },
  };
  const s = map[status];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium ${s.bg} ${s.text}`}>
      {status === 'processing' && (
        <svg className="animate-spin" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <circle cx="12" cy="12" r="10" strokeOpacity="0.2" />
          <path d="M12 2a10 10 0 019.95 9" />
        </svg>
      )}
      {s.label}
      {chunks !== undefined && status === 'ready' && (
        <span className="font-mono text-[10px] opacity-70">{chunks} 块</span>
      )}
    </span>
  );
}

// ── utils ──

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
}
