from pydantic import BaseModel, field_validator


class ComentarioIn(BaseModel):
    texto: str

    @field_validator("texto")
    @classmethod
    def _no_vacio(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("el comentario no puede estar vacío")
        return v
