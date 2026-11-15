import Link from "next/link";
import { FileArchive, FileImage, MessageSquareText } from "lucide-react";
import DemoLadder from "@/features/home/demo-ladder";

const CONDITIONS = [
  {
    name: "Spinal canal stenosis",
    sequence: "Sagittal T2 or STIR",
    detail: "Narrowing of the central canal, graded at each disc level.",
  },
  {
    name: "Neural foraminal narrowing",
    sequence: "Sagittal T1",
    detail: "Narrowing where the exiting nerve root leaves, graded left and right.",
  },
  {
    name: "Subarticular stenosis",
    sequence: "Axial T2",
    detail: "Narrowing of the lateral recess, graded left and right.",
  },
];

export default function Home() {
  return (
    <div className="mx-auto max-w-[90rem] px-4 sm:px-6">
      <section className="grid gap-10 py-12 lg:grid-cols-[1.05fr_1fr] lg:items-center lg:py-20">
        <div>
          <h1 className="max-w-[16ch] text-[clamp(2.4rem,5vw,4.1rem)] font-bold leading-[1.02] tracking-[-0.03em]">
            Every lumbar level, graded and explained.
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-graphite">
            Upload a lumbar MRI series. SpineScope locates L1/L2 to L5/S1, grades stenosis at each
            level as normal or mild, moderate or severe, and shows the image evidence behind every
            grade.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/multi-scan" className="btn btn-primary px-5 py-3 text-base">
              <FileArchive size={19} /> Grade a full series
            </Link>
            <Link href="/single-scan" className="btn btn-quiet px-5 py-3 text-base">
              <FileImage size={19} /> Grade one slice
            </Link>
          </div>
        </div>
        <DemoLadder />
      </section>

      <section className="border-t border-rule py-12" aria-labelledby="conditions">
        <h2 id="conditions" className="text-2xl font-bold tracking-tight">
          Three conditions, read from the sequence you upload
        </h2>
        <dl className="mt-6 grid gap-x-10 gap-y-6 md:grid-cols-3">
          {CONDITIONS.map((item) => (
            <div key={item.name} className="border-l-4 border-cobalt pl-4">
              <dt className="font-semibold">{item.name}</dt>
              <dd className="mt-1 text-sm text-cobalt-deep">{item.sequence}</dd>
              <dd className="mt-2 text-graphite">{item.detail}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section
        className="grid gap-10 border-t border-rule py-12 lg:grid-cols-2"
        aria-labelledby="flow"
      >
        <div>
          <h2 id="flow" className="text-2xl font-bold tracking-tight">
            How a series is read
          </h2>
          <ol className="mt-6 space-y-5">
            {[
              ["Locate", "A 3D model finds the five disc levels across all slices."],
              ["Refine", "A second model sharpens each level's position on its slice."],
              ["Grade", "A classifier grades a crop around each level and maps where it looked."],
            ].map(([title, text], index) => (
              <li key={title} className="flex gap-4">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink font-bold text-white">
                  {index + 1}
                </span>
                <div>
                  <p className="font-semibold">{title}</p>
                  <p className="text-graphite">{text}</p>
                </div>
              </li>
            ))}
          </ol>
          <Link
            href="/about"
            className="mt-6 inline-block font-semibold text-cobalt-deep underline"
          >
            Models, limits and validation status
          </Link>
        </div>
        <div className="panel flex flex-col justify-between gap-6 p-6">
          <div>
            <MessageSquareText className="text-cobalt" />
            <h2 className="mt-3 text-xl font-bold">Talk a result through</h2>
            <p className="mt-2 text-graphite">
              Send a result to the assistant and ask what a grade means, which level matters most,
              or how it relates to symptoms. Answers in English or Urdu, with your earlier
              conversations kept in a history you can search and edit.
            </p>
          </div>
          <Link href="/assistant" className="btn btn-quiet self-start">
            Open the assistant
          </Link>
        </div>
      </section>
    </div>
  );
}
