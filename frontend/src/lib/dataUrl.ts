/** URL of a file in ./data, stamped with this build's id so caches can't serve an older deploy's copy. */
export function dataUrl(path: string): string {
  const v = import.meta.env.VITE_BUILD_ID as string | undefined;
  return `./data/${path}${v ? `?v=${v}` : ""}`;
}
