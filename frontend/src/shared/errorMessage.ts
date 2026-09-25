import { ApiError } from "../api/client";

export function getErrorMessage(error: unknown, fallback = "Неуспешно зареждане. Опитайте отново."): string {
  return error instanceof ApiError ? error.message : fallback;
}
