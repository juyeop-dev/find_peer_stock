import {useSyncExternalStore} from "react";
import {historyPublicationSnapshot, subscribeHistoryPublication} from "./historyAvailability";
export function useHistoryAvailability() {
  return useSyncExternalStore(subscribeHistoryPublication, historyPublicationSnapshot, historyPublicationSnapshot);
}
