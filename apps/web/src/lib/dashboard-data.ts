
import {
  Activity,
  BookOpen,
  Database,
  FileSearch,
  Fingerprint,
  Network,
  SearchCheck,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface DashboardCard {
  title: string;
  description: string;
  icon: LucideIcon;
}

export interface PipelineStage extends DashboardCard {
  number: string;
}

export const pipelineStages: readonly PipelineStage[] = [
  {
    number: "01",
    title: "Evidence Retrieval",
    description:
      "Retrieve relevant material through lexical search, dense embeddings, and neural reranking.",
    icon: FileSearch,
  },
  {
    number: "02",
    title: "Evidence Assessment",
    description:
      "Use natural language inference and admissibility rules to evaluate supporting and refuting evidence.",
    icon: SearchCheck,
  },
  {
    number: "03",
    title: "Cross-Source Analysis",
    description:
      "Examine provenance, publication context, repeated reporting, and source-independence uncertainty.",
    icon: Network,
  },
];

export const capabilities: readonly DashboardCard[] = [
  {
    title: "Source Provenance",
    description:
      "Track document identity, captured passages, and source metadata.",
    icon: Fingerprint,
  },
  {
    title: "Explainable Decisions",
    description:
      "Expose relevant evidence, reasoning signals, and abstention conditions.",
    icon: BookOpen,
  },
  {
    title: "Reliability Evaluation",
    description:
      "Measure verification quality and investigate incorrect or uncertain outcomes.",
    icon: Activity,
  },
  {
    title: "Persistent Evidence",
    description:
      "Store auditable verification and provenance records in PostgreSQL.",
    icon: Database,
  },
];
