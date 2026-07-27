import { Center, Paper, Stack, Text, Title } from "@mantine/core";

/** Aterrizaje de admin y gerente hasta F8b. */
export function PlaceholderAdmin() {
  return (
    <Center mt={80}>
      <Paper withBorder p="xl" w={460}>
        <Stack gap="xs">
          <Title order={3}>CRM / Administración</Title>
          <Text c="dimmed">
            Disponible próximamente. Los dashboards, la tabla global con export y la
            administración llegan en la siguiente fase (F8b).
          </Text>
        </Stack>
      </Paper>
    </Center>
  );
}
