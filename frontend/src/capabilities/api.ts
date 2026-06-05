import { apiUrl, readResponse } from "../api";
import type { Capabilities } from "./types";

export async function fetchCapabilities(): Promise<Capabilities> {
  const response = await fetch(apiUrl("/capabilities"));
  return readResponse<Capabilities>(response);
}
