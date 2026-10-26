import { useId } from 'react';

export default function Mascot({ size = 'medium', className = '' }) {
  const id = useId().replaceAll(':', '');
  const roof = `${id}-roof`;
  const body = `${id}-body`;
  const limb = `${id}-limb`;
  const shade = `${id}-shadow`;

  return (
    <svg
      className={`little-homi little-homi--${size} ${className}`}
      viewBox="0 0 240 260"
      role="img"
      aria-label="Little Homi, your friendly AI household companion"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={roof} x1="45" y1="34" x2="194" y2="116" gradientUnits="userSpaceOnUse">
          <stop stopColor="#F1A273" />
          <stop offset=".48" stopColor="#D77853" />
          <stop offset="1" stopColor="#B95743" />
        </linearGradient>
        <linearGradient id={body} x1="71" y1="72" x2="176" y2="200" gradientUnits="userSpaceOnUse">
          <stop stopColor="#FFF8E8" />
          <stop offset=".62" stopColor="#F7EBD6" />
          <stop offset="1" stopColor="#E9D9BF" />
        </linearGradient>
        <linearGradient id={limb} x1="80" y1="175" x2="166" y2="234" gradientUnits="userSpaceOnUse">
          <stop stopColor="#F9EDD8" />
          <stop offset="1" stopColor="#E5D4B9" />
        </linearGradient>
        <radialGradient id={shade} cx="0" cy="0" r="1" gradientTransform="matrix(0 12 -69 0 120 233)" gradientUnits="userSpaceOnUse">
          <stop stopColor="#405642" stopOpacity=".2" />
          <stop offset="1" stopColor="#405642" stopOpacity="0" />
        </radialGradient>
        <filter id={`${id}-lift`} x="21" y="14" width="198" height="238" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
          <feDropShadow dx="0" dy="7" stdDeviation="6" floodColor="#634B38" floodOpacity=".16" />
        </filter>
      </defs>

      <ellipse cx="120" cy="233" rx="69" ry="12" fill={`url(#${shade})`} />
      <g filter={`url(#${id}-lift)`}>
        <path d="M91 189v38a8 8 0 0 0 16 0v-38M135 189v38a8 8 0 0 0 16 0v-38" fill={`url(#${limb})`} />
        <path d="M66 143c-16 2-25 13-25 27 0 10 6 16 14 16 9 0 16-8 21-20M174 143c16 2 25 13 25 27 0 10-6 16-14 16-9 0-16-8-21-20" fill={`url(#${limb})`} />

        <path d="m56 103 58-51a9 9 0 0 1 12 0l58 51v74a20 20 0 0 1-20 20H76a20 20 0 0 1-20-20v-74Z" fill={`url(#${body})`} stroke="#D8C8AD" strokeWidth="2.5" />
        <path d="M68 108v64c0 9 7 16 16 16h69" fill="none" stroke="#FFFDF4" strokeOpacity=".62" strokeWidth="4" strokeLinecap="round" />
        <path d="m47 108 66-69a10 10 0 0 1 14 0l66 69c4 4 3 10-1 14l-6 6-66-66-66 66-6-6c-4-4-5-10-1-14Z" fill={`url(#${roof})`} />
        <path d="m60 104 57-60a4 4 0 0 1 6 0l57 60" fill="none" stroke="#FFD0A2" strokeOpacity=".6" strokeWidth="4" strokeLinecap="round" />
        <path d="M47 108c-3 4-2 9 2 12l5 5 9-9M193 108c3 4 2 9-2 12l-5 5-9-9" fill="none" stroke="#B85D48" strokeWidth="3" strokeLinecap="round" />

        <path d="M92 134c5 7 12 7 17 0M131 134c5 7 12 7 17 0" fill="none" stroke="#53634E" strokeWidth="4.5" strokeLinecap="round" />
        <path d="M105 153c8 10 22 10 30 0" fill="none" stroke="#53634E" strokeWidth="4" strokeLinecap="round" />
        <ellipse cx="82" cy="148" rx="7" ry="4.5" fill="#D88777" opacity=".48" />
        <ellipse cx="158" cy="148" rx="7" ry="4.5" fill="#D88777" opacity=".48" />
        <path d="M64 232h23M153 232h23" stroke="#C5AD8C" strokeWidth="3" strokeLinecap="round" opacity=".65" />
      </g>
      <path d="M35 142c-6 5-8 11-7 18 6-3 10-8 11-15M205 142c6 5 8 11 7 18-6-3-10-8-11-15" fill="#E9EFE0" stroke="#8FA084" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M116 24c0-7 5-12 12-12" fill="none" stroke="#819479" strokeWidth="3" strokeLinecap="round" />
      <circle cx="131" cy="11" r="5" fill="#E1AE65" />
    </svg>
  );
}
