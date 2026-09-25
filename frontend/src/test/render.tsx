import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions, type RenderResult } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

export interface TestRenderOptions extends Omit<RenderOptions, "wrapper"> {
  initialEntries?: string[];
  route?: string;
}

export interface TestRenderResult extends RenderResult {
  queryClient: QueryClient;
}

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}

/** Renders a component with isolated TanStack Query and in-memory routing state. */
/** Renders a component with isolated read-only query and in-memory routing state. */
export function renderWithProviders(
  ui: ReactNode,
  { initialEntries, route = "/", ...renderOptions }: TestRenderOptions = {},
): TestRenderResult {
  const queryClient = createTestQueryClient();
  const result = render(ui, {
    ...renderOptions,
    wrapper: ({ children }) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={initialEntries ?? [route]}>{children}</MemoryRouter>
      </QueryClientProvider>
    ),
  });

  return { ...result, queryClient };
}
