import { memo, useState, useRef, useCallback, useEffect } from 'react';

interface ChatInputProps {
  onSend: (query: string, image?: string) => void;
  onAbort: () => void;
  isProcessing: boolean;
}

export default memo(function ChatInput({ onSend, onAbort, isProcessing }: ChatInputProps) {
  const [value, setValue] = useState('');
  const [image, setImage] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const autoResize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 140) + 'px';
  }, []);

  useEffect(() => { autoResize(); }, [value, autoResize]);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    const hasImage = image !== null;
    if ((!trimmed && !hasImage) || isProcessing) return;
    onSend(trimmed || '帮我描述这张图片', image || undefined);
    setValue('');
    setImage(null);
    setImagePreview(null);
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  }, [value, image, isProcessing, onSend]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }, [handleSend]);

  const handleImagePick = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) { alert('图片最大 10MB'); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const b64 = (reader.result as string).split(',')[1]; // strip "data:image/png;base64,"
      setImage(b64);
      setImagePreview(reader.result as string);
    };
    reader.readAsDataURL(file);
    e.target.value = '';
  }, []);

  const clearImage = useCallback(() => { setImage(null); setImagePreview(null); }, []);

  const hasContent = value.trim().length > 0 || image !== null;

  return (
    <div className="px-5 py-4 border-t border-surface-border bg-white/80 backdrop-blur-sm flex-shrink-0">
      {/* Image preview */}
      {imagePreview && (
        <div className="mb-3 inline-flex relative animate-fade-in">
          <img src={imagePreview} alt="预览" className="h-20 rounded-xl border border-surface-border object-cover" />
          <button
            onClick={clearImage}
            className="absolute -top-2 -right-2 w-5 h-5 bg-red-500 text-white rounded-full flex items-center justify-center text-[10px] hover:bg-red-600 transition-colors"
          >
            ×
          </button>
        </div>
      )}

      <div className={`flex items-end gap-3 bg-white border rounded-2xl px-4 py-3 transition-all duration-200
        ${hasContent ? 'border-primary-300 shadow-sm shadow-primary-100' : 'border-surface-border hover:border-surface-hover'}
        focus-within:border-primary-400 focus-within:shadow-sm focus-within:shadow-primary-100`}>
        {/* Image upload button */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={isProcessing}
          className="flex-shrink-0 w-9 h-9 rounded-full bg-surface-raised text-ink-muted hover:text-primary-500 hover:bg-primary-50 flex items-center justify-center transition-all duration-150 disabled:opacity-50"
          title="上传图片"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <polyline points="21 15 16 10 5 21" />
          </svg>
        </button>
        <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleImagePick} />

        <textarea
          ref={textareaRef}
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={image ? "为图片添加描述（可选）…" : "输入你的问题，Agent 将从知识库中检索并回答…"}
          rows={1}
          className="flex-1 resize-none bg-transparent outline-none text-[15px] leading-relaxed text-ink-strong
                     placeholder:text-ink-dim max-h-[140px]"
        />

        {isProcessing ? (
          <button onClick={onAbort}
            className="flex-shrink-0 w-9 h-9 rounded-full bg-red-100 border border-red-200
                       text-red-500 flex items-center justify-center
                       hover:bg-red-200 transition-all duration-150"
            title="停止生成">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <rect x="4" y="4" width="16" height="16" rx="2" />
            </svg>
          </button>
        ) : (
          <button onClick={handleSend} disabled={!hasContent}
            className={`flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center transition-all duration-200
              ${hasContent
                ? 'bg-primary-500 text-white hover:bg-primary-600 hover:scale-105 active:scale-95 shadow-sm shadow-primary-200'
                : 'bg-surface-raised text-ink-dim cursor-not-allowed'
              }`}
            title="发送 (Enter)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="19" x2="12" y2="5" />
              <polyline points="5 12 12 5 19 12" />
            </svg>
          </button>
        )}
      </div>
      <p className="text-[11px] text-ink-dim mt-2.5 text-center">
        Enter 发送 · Shift+Enter 换行 · 支持上传图片解析
      </p>
    </div>
  );
});
