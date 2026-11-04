/** "Sources checked 4 Nov 2026, 9:54 am": the time is shown in the reader's own time zone (it can differ from the
 *  server's, so the text may change once the page loads). */
export function CheckedAt({ iso, prefix = "Sources last checked" }: { iso: string | null | undefined; prefix?: string }) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const text = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" }).format(d);
  return (
    <span className="checked-at">
      {prefix} <time dateTime={iso} suppressHydrationWarning>{text}</time>
    </span>
  );
}
