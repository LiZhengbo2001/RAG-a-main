import { memo } from 'react';

interface ProtectedRouteProps {
  token: string | null;
  loading: boolean;
  children: React.ReactNode;
  loginSlot: React.ReactNode;
}

export default memo(function ProtectedRoute({
  token,
  loading,
  children,
  loginSlot,
}: ProtectedRouteProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-surface-muted">
        <div className="flex flex-col items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center shadow-sm shadow-primary-200">
            <span className="text-white font-mono text-xl font-medium">R</span>
          </div>
          <div className="flex gap-1.5">
            {[0, 1, 2].map(i => (
              <span
                key={i}
                className="w-2 h-2 rounded-full bg-primary-400 animate-bounce-dot"
                style={{ animationDelay: `${i * 0.2}s` }}
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!token) {
    return <>{loginSlot}</>;
  }

  return <>{children}</>;
});
