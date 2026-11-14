export function relativeTime(iso: string): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} 天前`;
  return new Date(iso).toLocaleDateString("zh-CN");
}

export function maskEmail(email: string): string {
  const [user, domain] = email.split("@");
  if (!domain || user.length <= 3) return email;
  return `${user.slice(0, 3)}***@${domain}`;
}

export function groupInitials(email: string): string {
  const handle = email.split("@")[0] ?? "";
  const parts = handle.split(/[._-]+/).filter(Boolean);
  const letters = (parts.length > 1 ? parts[0][0] + parts[1][0] : handle.slice(0, 2)) || "?";
  return letters.toUpperCase();
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
