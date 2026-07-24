from pydantic import BaseModel, ConfigDict


class ClienteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_normalizado: str
