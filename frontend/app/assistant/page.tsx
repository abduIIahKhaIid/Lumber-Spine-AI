import type { Metadata } from "next";
import { Suspense } from "react";
import AssistantApp from "@/features/chat/assistant-app";

export const metadata: Metadata = { title: "Assistant" };

export default function AssistantPage() {
  return (
    <Suspense fallback={null}>
      <AssistantApp />
    </Suspense>
  );
}
