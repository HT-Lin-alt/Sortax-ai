import {
  type PropsWithChildren,
  useMemo,
  useReducer,
} from "react";

import { AppContext } from "./app-context";
import { appReducer, initialAppState } from "./app-reducer";

export function AppProvider({ children }: PropsWithChildren) {
  const [state, dispatch] = useReducer(appReducer, initialAppState);
  const value = useMemo(() => ({ state, dispatch }), [state]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
