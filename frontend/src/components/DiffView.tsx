// Minimal unified-diff renderer: colors +/- lines, dims @@ hunks. No external
// syntax-highlighting dep (CSP-friendly, tiny).

function lineClass(line: string): string {
  if (line.startsWith("+") && !line.startsWith("+++")) return "bg-emerald-50 text-emerald-800";
  if (line.startsWith("-") && !line.startsWith("---")) return "bg-rose-50 text-rose-800";
  if (line.startsWith("@@")) return "bg-slate-100 text-slate-500";
  return "text-slate-700";
}

export function DiffView({ diff }: { diff: string }) {
  const lines = diff.replace(/\n$/, "").split("\n");
  return (
    <pre className="overflow-x-auto rounded-md border border-slate-200 bg-white text-xs leading-5">
      <code>
        {lines.map((line, i) => (
          <div key={i} className={`px-3 ${lineClass(line)}`}>
            {line || " "}
          </div>
        ))}
      </code>
    </pre>
  );
}
