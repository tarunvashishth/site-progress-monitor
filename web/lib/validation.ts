export const ALLOWED_EXT: Record<string, string> = { ".mp4": "video/mp4", ".mov": "video/quicktime" };
export const MAX_VIDEO_BYTES = Number(process.env.NEXT_PUBLIC_MAX_VIDEO_MB ?? 2048) * 1024 * 1024;

export function validateVideoFile(file: { name: string; size: number; type: string }, maxBytes = MAX_VIDEO_BYTES): string | null {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!(ext in ALLOWED_EXT)) return "Only MP4 and MOV videos are supported.";
  if (file.type && file.type !== ALLOWED_EXT[ext]) return "The file type does not match its extension.";
  if (file.size <= 0) return "The file is empty.";
  if (file.size > maxBytes) return `The file exceeds the ${Math.round(maxBytes / 1024 / 1024)} MB limit.`;
  return null;
}

export function weightsTotal(rows: { weight_percentage: string | number }[]): number {
  return Math.round(rows.reduce((a, r) => a + (Number(r.weight_percentage) || 0), 0) * 100) / 100;
}

export const fmtPct = (n: number | null | undefined) => (n == null ? "—" : `${Number(n).toFixed(1).replace(/\.0$/, "")}%`);
export const fmtTime = (s: number) => new Date(s * 1000).toISOString().slice(11, 19);
export const fmtDate = (d: string | null | undefined) =>
  d ? new Date(d).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—";

export const MAX_REFERENCE_BYTES = 10 * 1024 * 1024;
export const MAX_REFERENCES = 6;
export function validateReferenceFile(file: { size: number; type: string }): string | null {
  if (file.type !== "image/jpeg" && file.type !== "image/png") return "Reference images must be JPEG or PNG.";
  if (file.size <= 0) return "The file is empty.";
  if (file.size > MAX_REFERENCE_BYTES) return "The image exceeds the 10 MB limit.";
  return null;
}
export const BASIS_LABEL: Record<string, string> = {
  visible_work: "visible work", target_comparison: "comparison with the finished-site reference", both: "visible work and the finished-site reference",
};
