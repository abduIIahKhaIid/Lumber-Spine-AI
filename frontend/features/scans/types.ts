import type { Severity } from "@/lib/severity";

export type ScanMode = "single" | "multi";

export type Explanation = {
  crop_image: string | null;
  heatmap_image: string | null;
  method: string;
  color?: string;
  note?: string;
};

export type Finding = {
  id: string;
  key: string;
  condition: "SCS" | "NFN" | "SS";
  condition_name: string;
  level: string;
  side: "left" | "right" | null;
  level_label: string;
  severity: Severity;
  severity_confidence: number;
  class_scores: Record<Severity, number>;
  localization_confidence: number | null;
  box: [number, number, number, number];
  point: [number, number];
  image_index: number;
  slice_number: number | null;
  uncertainty: { status: "review" | "no_flag"; reasons: string[]; method: string };
  calibration: { status: string; scores: Partial<Record<Severity, number>>; reason?: string };
  explanation: Explanation;
};

export type ScanImage = {
  index: number;
  slice_number: number | null;
  width: number;
  height: number;
  original: string;
  annotated: string;
};

export type Recommendation = {
  id: string;
  priority: "high" | "medium" | "low";
  category: string;
  title: string;
  clinician: string;
  patient: string;
  evidence: string[];
  rules_version?: string;
};

export type Quality = {
  status: "pass" | "review";
  issues: string[];
  notes?: string[];
  method: string;
  dimensions?: number[];
  slice_count?: number;
};

export type AnalysisResult = {
  analysis_id: string;
  mode: ScanMode;
  condition: "SCS" | "NFN" | "SS";
  condition_name: string;
  plane: string;
  sequence: string;
  images: ScanImage[];
  findings: Finding[];
  summary: {
    counts: Record<Severity, number>;
    total: number;
    max_severity: Severity | null;
    flagged: number;
    not_assessed: string[];
  };
  quality: Quality;
  recommendations: Recommendation[];
  provenance: Record<string, unknown> & {
    pipeline_version?: string;
    calibration?: string;
    checkpoints_sha256?: Record<string, string>;
  };
  slice_count?: number;
  created_at: string;
};

export type JobStatus = {
  id: string;
  state: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  message: string;
  result?: AnalysisResult;
  error?: string;
};
