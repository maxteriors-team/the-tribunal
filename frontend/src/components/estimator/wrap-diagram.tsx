/**
 * The measured tree, drawn.
 *
 * A rep quoting a wrap has to hold four numbers in their head at once — height,
 * width, how tight the rows are, how many there will be — and a column of
 * number inputs shows none of it. This draws the actual thing being priced:
 * the silhouette they picked, with the real computed rows across it at their
 * real spacing. Tightening row spacing visibly packs the lines together, so the
 * number the customer is being charged for becomes something the rep can see
 * rather than imagine.
 *
 * One shape vocabulary serves every size: the small tiles the rep chooses from,
 * the large live drawing they end up with, and the lights painted on the
 * customer's photo — all from `WRAP_PROFILE`. The picture on the button is the
 * picture they get, and the picture the customer approves.
 */
import { WRAP_PROFILE, WRAP_TOP_INSET, type WrapShape } from "@/lib/estimator/tree-wrap";

function outline(shape: WrapShape, width: number, height: number, top: number): string {
  const profile = WRAP_PROFILE[shape];
  const midX = width / 2;
  const steps = 24;
  const left: string[] = [];
  const right: string[] = [];
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps;
    const y = top + t * (height - top);
    const halfWidth = profile(t) * midX * 0.92;
    left.push(`${midX - halfWidth},${y}`);
    right.push(`${midX + halfWidth},${y}`);
  }
  return `M${left.join(" L")} L${right.reverse().join(" L")} Z`;
}

interface WrapDiagramProps {
  shape: WrapShape;
  /** Wrap rows to draw across the shape. Omit for a plain silhouette. */
  rowCount?: number;
  width?: number;
  height?: number;
  /** Decorative inside a labelled control; named when it stands alone. */
  title?: string;
}

export function WrapDiagram({
  shape,
  rowCount,
  width = 92,
  height = 104,
  title,
}: WrapDiagramProps) {
  const top = WRAP_TOP_INSET[shape] * height;
  const profile = WRAP_PROFILE[shape];
  const midX = width / 2;

  // Drawing 200 rows in a 100px box is a grey smear, not information. Past the
  // point where rows would collide, draw evenly spaced representative lines and
  // let the readout carry the exact count.
  const requested = rowCount ?? 0;
  const drawn = Math.min(requested, Math.max(3, Math.floor((height - top) / 4)));

  const rows = Array.from({ length: drawn }, (_, index) => {
    const t = drawn === 1 ? 0.5 : (index + 0.5) / drawn;
    const y = top + t * (height - top);
    const halfWidth = profile(t) * midX * 0.92;
    return { y, halfWidth };
  });

  const trunkTop = shape === "deciduous" ? top + (height - top) * 0.78 : null;

  return (
    <svg
      className="tp-wrap-diagram"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role={title ? "img" : "presentation"}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      {trunkTop !== null ? (
        <line
          x1={midX}
          y1={trunkTop}
          x2={midX}
          y2={height}
          className="tp-wrap-diagram-trunk"
          strokeWidth={Math.max(3, width * 0.06)}
        />
      ) : null}
      <path d={outline(shape, width, height, top)} className="tp-wrap-diagram-body" />
      {rows.map(({ y, halfWidth }, index) => (
        <line
          key={index}
          x1={midX - halfWidth}
          y1={y}
          x2={midX + halfWidth}
          y2={y}
          className="tp-wrap-diagram-row"
        />
      ))}
    </svg>
  );
}
