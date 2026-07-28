/** Stack de providers de la app (F8e). ORDEN CRÍTICO: QueryClientProvider va
 * FUERA de ModalsProvider — el contenido de modals.open se monta en el portal
 * del ModalsProvider y solo ve los contextos que estén POR ENCIMA de él; con
 * el orden invertido, cualquier modal con hooks de TanStack Query truena con
 * "No QueryClient set" (bug F8e punto 0, cubierto en modal-providers.test). */

import { MantineProvider } from "@mantine/core";
import { DatesProvider } from "@mantine/dates";
import { ModalsProvider } from "@mantine/modals";
import { Notifications, notifications } from "@mantine/notifications";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ApiError } from "./lib/api";
import { theme } from "./theme";

export function crearQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 1, staleTime: 15_000, refetchOnWindowFocus: false },
    },
    // Handler GLOBAL de errores de mutación (F8d): las vistas no repiten
    // notifications.show. Una mutación que maneja su propio error (p. ej. el
    // 409 de baja segura abre un modal) lo declara con meta.errorManejado.
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (mutation.meta?.errorManejado) return;
        notifications.show({
          message: error instanceof ApiError ? error.detail : "Error inesperado",
          color: "red",
        });
      },
    }),
  });
}

const queryClient = crearQueryClient();

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <MantineProvider theme={theme}>
      <DatesProvider settings={{ locale: "es-mx" }}>
        <QueryClientProvider client={queryClient}>
          <ModalsProvider>
            <Notifications position="top-right" />
            {children}
          </ModalsProvider>
        </QueryClientProvider>
      </DatesProvider>
    </MantineProvider>
  );
}
