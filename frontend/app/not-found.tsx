import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-xl px-4 py-24 text-center">
      <h1 className="text-3xl font-bold">This page does not exist</h1>
      <p className="mt-3 text-graphite">Check the address, or start from a scan.</p>
      <Link href="/" className="btn btn-primary mt-6">
        Go to the start page
      </Link>
    </div>
  );
}
