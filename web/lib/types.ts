export type Role = "admin" | "client";
export interface Me { id: string; email: string; full_name: string; role: Role }
export interface Page<T> { items: T[]; total: number; limit: number; offset: number }

export interface PackageProgress {
  work_package_id: string; name: string; description?: string | null;
  weight_percentage: number; approved_percentage: number;
}
export interface LatestReport { id: string; published_at: string; summary: string; assessment_coverage_percentage: number }
export interface ProjectSummary {
  id: string; name: string; location: string | null; status: string; start_date: string | null;
  overall_progress: number; latest_report: LatestReport | null;
}
export interface ProjectDetail extends ProjectSummary {
  description: string | null;
  work_packages: PackageProgress[];
  history: { id: string; published_at: string; overall_progress_percentage: number; assessment_coverage_percentage: number }[];
}
export interface Dashboard {
  total_projects: number; active_projects: number; total_videos: number; reports_awaiting_review: number;
  recent_activity: { kind: string; id: string; project: string; detail: string; at: string }[];
}
export interface VideoRow {
  id: string; original_filename: string; capture_date: string; description: string | null; status: string;
  processing_error: string | null; duration_seconds: number | null; file_size: number | null;
  job_status: string | null; job_type: string | null; attempts: number | null; job_error: string | null;
  report_id: string | null; report_status: string | null;
}
export interface Evidence { frame_id: string; frame_index: number; timestamp_seconds: number; thumb_url?: string | null }
export interface Observation {
  id: string; title: string; description: string; category: string; observation_type: string;
  confidence?: number; review_status?: "pending" | "approved" | "rejected"; work_package_id?: string | null;
  work_package_name?: string | null; evidence: Evidence[]; evidence_frames?: Evidence[]; edited_by?: string | null;
}
export interface AnalysisView {
  video: VideoRow & { project_id: string };
  job: { status: string; error_message: string | null; job_type: string } | null;
  analysis: { id: string; status: string; model_name: string; prompt_version: string; error_message: string | null;
              structured_response: { summary?: string; validation_warnings?: string[] } | null } | null;
  observations: (Observation & { evidence_frames: Evidence[] })[];
  frames: { id: string; frame_index: number; timestamp_seconds: number; thumb_url: string | null }[];
  ai_configured: boolean;
}
export interface ReportItem {
  work_package_id: string; name: string; weight_percentage: number; previous_approved_percentage: number;
  approved_percentage: number | null; assessed: boolean; decision?: "pending" | "accept" | "edit" | "retain";
  ai?: { assessable: boolean; proposed_completion_percentage: number | null; confidence: number; reasoning: string } | null;
}
export interface Report {
  id: string; project_id: string; video_id: string; status: "draft" | "published"; summary: string;
  capture_date: string; published_at: string | null; overall_progress_percentage: number;
  assessment_coverage_percentage: number; retained_package_count: number; video_url: string;
  work_packages: ReportItem[]; observations: Observation[]; pending_packages?: string[];
}
export interface ReportRow {
  id: string; video_id: string; status: "draft" | "published"; summary: string; capture_date: string;
  overall_progress_percentage: number | null; assessment_coverage_percentage: number | null; published_at: string | null;
}
