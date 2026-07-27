import { Button } from "@mantine/core";
import { useNavigate } from "react-router";

import { rutaPorRol, useAuth } from "../auth/AuthContext";

/** "← Volver": historial si lo hay; si se entró directo, al home del rol. */
export function VolverBoton() {
  const navigate = useNavigate();
  const { usuario } = useAuth();
  return (
    <Button
      variant="subtle"
      color="gray"
      size="compact-sm"
      onClick={() => {
        if (window.history.length > 1) navigate(-1);
        else navigate(usuario ? rutaPorRol(usuario.rol) : "/");
      }}
    >
      ← Volver
    </Button>
  );
}
