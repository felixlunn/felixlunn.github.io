import { memo } from "react";

interface Props {
  values: (number | null)[];
  selected: number | null;
  national: number | null;
  label: string;
}

/** Distribution strip: every seat as a faint tick, national figure as a line, the selected seat as a dot. */
function Strip({ values, selected, national, label }: Props) {
  const W = 84, H = 18;
  const vals = values.filter((v): v is number => v !== null);
  if (!vals.length) return <svg width={W} height={H} aria-hidden="true" />;
  let min = Infinity, max = -Infinity;
  for (const v of vals) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  const x = (v: number) => (max === min ? W / 2 : 4 + ((v - min) / (max - min)) * (W - 8));
  const sel = selected !== null ? values[selected] : null;
  return (
    <svg width={W} height={H} className="strip" role="img" aria-label={label}>
      <title>{label}</title>
      <path d={vals.map((v) => `M${x(v).toFixed(1)} 5V13`).join("")} className="strip-tick" />
      {national !== null && national >= min && national <= max && (
        <line x1={x(national)} x2={x(national)} y1={1} y2={17} className="strip-nat" />
      )}
      {sel !== null && sel !== undefined && <circle cx={x(sel)} cy={9} r={4.5} className="strip-dot" />}
    </svg>
  );
}

export default memo(Strip);
