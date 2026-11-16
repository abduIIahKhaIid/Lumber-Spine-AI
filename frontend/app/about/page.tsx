import type { Metadata } from "next";
import Link from "next/link";
import SeriesToGrade from "@/features/about/series-to-grade";

export const metadata: Metadata = { title: "How it works" };

const STAGES = [
  {
    title: "Read the series",
    text: "Every slice of the series is read, identifiers are removed in memory and the slices are stacked in order.",
  },
  {
    title: "Locate the levels in 3D",
    text: "The whole series is resampled into a volume (32 slices for sagittal, 96 for axial). A 3D MobileNetV3 predicts where each disc level sits: left-right, up-down and which slice.",
  },
  {
    title: "Refine each position",
    text: "An EfficientNetV2-S looks at the chosen slice and its neighbours and moves each level point to a more precise spot.",
  },
  {
    title: "Grade the level",
    text: "A crop around each point is graded by a MobileNetV3 classifier with gated attention. Grad-CAM shows which pixels drove that grade, tinted green, yellow or red by the result.",
  },
];

const LIMITS = [
  "The models were trained on the RSNA 2024 Lumbar Spine Degenerative Classification data. Other scanners and populations may behave differently.",
  "Scores are raw model outputs, not calibrated probabilities, until a held-out evaluation is approved.",
  "Focus maps show model sensitivity. They do not prove where a lesion is.",
  "Single-slice mode only sees what that slice cuts through; a full series is more complete.",
  "Recommendations are review prompts from a draft rule set, not treatment advice.",
];

export default function AboutPage() {
  return (
    <article className="mx-auto max-w-3xl px-4 pb-20 pt-10 sm:px-6">
      <h1 className="text-[2.3rem] font-bold leading-tight tracking-tight">How SpineScope works</h1>
      <p className="mt-4 text-lg leading-relaxed text-graphite">
        SpineScope grades three degenerative conditions at the five lumbar disc levels, L1/L2 to
        L5/S1. The sequence you upload decides the condition: sagittal T2 or STIR for spinal canal
        stenosis, sagittal T1 for neural foraminal narrowing, axial T2 for subarticular stenosis.
      </p>

      <h2 className="mt-12 text-2xl font-bold">From series to grade</h2>
      <SeriesToGrade stages={STAGES} />
      <p className="mt-6 leading-relaxed text-graphite">
        A single slice skips the 3D steps: a YOLO detector finds the levels on that image and each
        one is graded the same way.
      </p>

      <h2 className="mt-12 text-2xl font-bold">Privacy</h2>
      <p className="mt-3 leading-relaxed text-graphite">
        Patient and staff identifiers are removed from the DICOM data in memory before analysis.
        Uploaded files are deleted as soon as the analysis finishes, and results expire after an
        hour unless you save the structured findings to a case. Saved cases never contain images.
      </p>

      <h2 className="mt-12 text-2xl font-bold">Limits</h2>
      <ul className="mt-3 list-disc space-y-2 pl-5 leading-relaxed text-graphite">
        {LIMITS.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      <p className="mt-12 rounded-xl border-l-4 border-sev-severe bg-paper p-4 leading-relaxed">
        SpineScope is research software, not a medical device. Every result must be reviewed by a
        qualified clinician together with the original images, history and examination.
      </p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link href="/multi-scan" className="btn btn-primary">
          Grade a full series
        </Link>
        <Link href="/assistant" className="btn btn-quiet">
          Ask the assistant
        </Link>
      </div>
    </article>
  );
}
