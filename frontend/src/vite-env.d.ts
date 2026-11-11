/// <reference types="vite/client" />
/// <reference types="msw/vite/client" />

interface ImportMetaEnv {
  /** Origin of the API when it is not served from the page's own origin. */
  readonly VITE_API_BASE_URL?: string;
  /** "true" answers /api requests with the mock API. Development only; ignored in a build. */
  readonly VITE_API_MOCKS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
