from __future__ import annotations

from onetl.impl.base_model import BaseModel


class FrozenModel(BaseModel):
    class Config:
        frozen = True
