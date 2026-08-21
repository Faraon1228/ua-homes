// Thin ESM wrapper around the self-hosted React UMD global (see
// web/vendor/react.production.min.js), mirroring web/react-shim.js so the
// admin bundle never pulls React in via npm or a CDN.
const ReactRef = globalThis.React;

export default ReactRef;
export const useEffect = ReactRef.useEffect;
export const useMemo = ReactRef.useMemo;
export const useRef = ReactRef.useRef;
export const useState = ReactRef.useState;
export const useCallback = ReactRef.useCallback;
export const useContext = ReactRef.useContext;
export const useReducer = ReactRef.useReducer;
export const createContext = ReactRef.createContext;
export const Fragment = ReactRef.Fragment;
export const Suspense = ReactRef.Suspense;
export const lazy = ReactRef.lazy;
export const useId = ReactRef.useId;
