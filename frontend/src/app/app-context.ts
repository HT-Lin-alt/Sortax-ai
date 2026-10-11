import { createContext, type Dispatch, useContext } from "react";

import type { AppAction, AppState } from "./app-reducer";

export interface AppContextValue {
  readonly state: AppState;
  readonly dispatch: Dispatch<AppAction>;
}

export const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const value = useContext(AppContext);
  if (value === null) {
    throw new Error("useApp must be used within AppProvider");
  }
  return value;
}
