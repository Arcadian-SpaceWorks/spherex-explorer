// Official CDS npm distribution; JS, CSS and WebAssembly bundled locally.
// Exact release and integrity are pinned in package.json/package-lock.json.
let loading;
export function loadAladin() {
  if (!loading) loading = import('aladin-lite').then(async ({default: A}) => {
    await A.init;
    return A;
  });
  return loading;
}
