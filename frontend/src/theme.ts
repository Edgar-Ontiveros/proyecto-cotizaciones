import { createTheme, type MantineColorsTuple } from "@mantine/core";

// Azul Herinox #2059A6 (primario) y naranja #F08215 (acento).
const herinoxAzul: MantineColorsTuple = [
  "#e8f0fb",
  "#cfddf1",
  "#9cb9e4",
  "#6693d8",
  "#3d74cd",
  "#2560c7",
  "#2059a6",
  "#134a94",
  "#074285",
  "#003976",
];

const herinoxNaranja: MantineColorsTuple = [
  "#fff0e2",
  "#ffdfcc",
  "#fabd9b",
  "#f69a66",
  "#f27c39",
  "#f1691c",
  "#f08215",
  "#d65f04",
  "#c05400",
  "#a74700",
];

export const theme = createTheme({
  primaryColor: "herinox",
  colors: {
    herinox: herinoxAzul,
    acento: herinoxNaranja,
  },
  defaultRadius: "md",
});
