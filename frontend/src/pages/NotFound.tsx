import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md py-24 text-center">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="mt-2 text-ink-muted">The page you're looking for doesn't exist or has moved.</p>
      <Link to="/" className="mt-6 inline-block rounded-ctl bg-nova-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-nova-700">Back to dashboard</Link>
    </div>
  );
}
