/** Shows summary text as bullet points. Lines starting with "-", "*" or "•" become list items;
 *  plain text without such lines is shown as a normal paragraph (older reports stay readable). */
export function summaryLines(text: string): { bullets: boolean; lines: string[] } {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const bullets = lines.some((l) => /^[-*•]\s+/.test(l));
  return { bullets, lines: lines.map((l) => l.replace(/^[-*•]\s+/, "")) };
}

export function Bullets({ text, className }: { text: string; className?: string }) {
  const { bullets, lines } = summaryLines(text);
  if (!bullets) return <p className={`whitespace-pre-wrap ${className ?? ""}`}>{text}</p>;
  return <ul className={`list-disc space-y-1 pl-5 ${className ?? ""}`}>{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>;
}
