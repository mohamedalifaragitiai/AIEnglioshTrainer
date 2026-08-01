/**
 * Loading placeholders.
 *
 * The dashboard fires five requests that land at different times, so without
 * these the page flickers through several layout shifts as each one arrives.
 * A placeholder of roughly the right shape holds the space its content will
 * take, which is the point — a spinner in the middle of an empty page does not.
 */

export function Line({ w = "100%", h = 12 }: { w?: string; h?: number }) {
  return (
    <span
      className="block rounded bg-panel2 animate-pulse my-2"
      style={{ width: w, height: h }}
    />
  );
}

export function TileSkeleton() {
  return (
    <div className="card">
      <Line w="40%" />
      <Line w="60%" h={26} />
      <Line w="50%" />
    </div>
  );
}

export function CardSkeleton({ height = 280 }: { height?: number }) {
  return (
    <div className="card">
      <Line w="30%" />
      <span
        className="block rounded-lg bg-panel2 animate-pulse mt-3"
        style={{ height }}
      />
    </div>
  );
}

export function DashboardSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading your dashboard…</span>
      <div className="card">
        <Line w="35%" />
        <Line w="80%" h={40} />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[0, 1, 2, 3].map((i) => (
          <TileSkeleton key={i} />
        ))}
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        <CardSkeleton />
        <CardSkeleton />
      </div>
    </div>
  );
}

export function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2.5" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 rounded-xl border border-line bg-panel px-4 py-3">
          <span className="rounded-lg bg-panel2 animate-pulse" style={{ width: 52, height: 34 }} />
          <span className="flex-1">
            <Line w="38%" />
            <Line w="62%" />
          </span>
        </div>
      ))}
    </div>
  );
}
