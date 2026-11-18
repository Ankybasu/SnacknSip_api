
from pydantic import BaseModel, Field
from typing import Optional, List


class OrderItemIn(BaseModel):
    menu_item_id: str
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    customer_phone: str = Field(min_length=5, max_length=20)
    items: List[OrderItemIn] = Field(min_items=1)
    notes: Optional[str] = None


class MenuItemCreate(BaseModel):
    name: str
    category: str
    price: float = Field(ge=0)
    is_available: bool = True
