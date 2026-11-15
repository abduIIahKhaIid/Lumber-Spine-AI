import type { Metadata } from "next";
import CaseLibrary from "@/features/cases/case-library";

export const metadata: Metadata = { title: "Cases" };

export default function CasesPage() {
  return (
    <div className="mx-auto max-w-[90rem] px-4 pb-16 pt-8 sm:px-6">
      <h1 className="text-[2rem] font-bold tracking-tight">Cases</h1>
      <p className="mt-1 max-w-2xl text-graphite">
        Review saved analyses level by level, record your impression and sign off. The original
        model output is never changed.
      </p>
      <div className="mt-6">
        <CaseLibrary />
      </div>
    </div>
  );
}
