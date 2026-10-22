// leaflet.gridlayer.googlemutant ships no bundled TypeScript types. It's a
// side-effect import that patches the global `L` object at runtime with
// `L.gridLayer.googleMutant(...)`, used imperatively in GISLeafletMap.tsx.
declare module "leaflet.gridlayer.googlemutant";

interface Window {
  google?: { maps?: unknown };
}
