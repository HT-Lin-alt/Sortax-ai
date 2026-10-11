export type ServiceStatus = "checking" | "available" | "unavailable";

export interface AppState {
  readonly serviceStatus: ServiceStatus;
  readonly requestId: string | null;
}

export type AppAction =
  | { readonly type: "health/check-started" }
  | { readonly type: "health/check-succeeded" }
  | { readonly type: "health/check-failed"; readonly requestId: string | null };

export const initialAppState: AppState = {
  serviceStatus: "checking",
  requestId: null,
};

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "health/check-started":
      return { ...state, serviceStatus: "checking", requestId: null };
    case "health/check-succeeded":
      return { ...state, serviceStatus: "available", requestId: null };
    case "health/check-failed":
      return { ...state, serviceStatus: "unavailable", requestId: action.requestId };
    default:
      return action satisfies never;
  }
}
