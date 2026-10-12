"""Модели данных, с которыми работает остальной код (а не с «сырыми» строками БД)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from utils.timeutil import from_db


class OrderMethod(StrEnum):
    DELIVERY = "delivery"
    PICKUP = "pickup"
    TABLE = "table"


class PaymentMethod(StrEnum):
    ONLINE = "online"
    CASH = "cash"
    CARD = "card"        # картой при получении
    ON_SITE = "on_site"  # за столиком — официанту


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"  # ждёт онлайн-оплаты, персонал его не видит
    NEW = "new"
    ACCEPTED = "accepted"
    COOKING = "cooking"
    READY = "ready"            # готов к выдаче (самовывоз / стол)
    ON_THE_WAY = "on_the_way"  # курьер выехал
    COMPLETED = "completed"    # выдан / доставлен
    REJECTED = "rejected"      # отклонён персоналом
    CANCELLED = "cancelled"    # отменён (например, не оплачен вовремя)


class BookingStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class SizeOption:
    code: str
    title: str
    price: int


@dataclass(frozen=True)
class Addon:
    code: str
    title: str
    price: int


@dataclass(frozen=True)
class Category:
    id: int
    title: str
    emoji: str
    sort: int

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.title}".strip()


@dataclass(frozen=True)
class MenuItem:
    id: int
    category_id: int
    title: str
    description: str
    price: int  # цена, если у блюда нет размеров
    photo: str | None  # путь в assets/, URL или file_id
    photo_file_id: str | None  # кэш file_id после первой отправки
    sizes: tuple[SizeOption, ...]
    addons: tuple[Addon, ...]
    is_available: bool
    sort: int

    @classmethod
    def from_row(cls, row) -> MenuItem:
        sizes = tuple(SizeOption(**s) for s in json.loads(row["sizes"] or "[]"))
        addons = tuple(Addon(**a) for a in json.loads(row["addons"] or "[]"))
        return cls(
            id=row["id"],
            category_id=row["category_id"],
            title=row["title"],
            description=row["description"],
            price=row["price"],
            photo=row["photo"],
            photo_file_id=row["photo_file_id"],
            sizes=sizes,
            addons=addons,
            is_available=bool(row["is_available"]),
            sort=row["sort"],
        )

    def get_size(self, code: str | None) -> SizeOption | None:
        for size in self.sizes:
            if size.code == code:
                return size
        return None

    @property
    def default_size(self) -> SizeOption | None:
        """Средний размер — самый популярный выбор."""
        if not self.sizes:
            return None
        return self.sizes[len(self.sizes) // 2] if len(self.sizes) > 2 else self.sizes[0]

    def get_addons(self, codes: list[str] | tuple[str, ...]) -> list[Addon]:
        """Добавки по кодам в порядке меню; несуществующие коды отбрасываются."""
        wanted = set(codes)
        return [a for a in self.addons if a.code in wanted]

    @property
    def min_price(self) -> int:
        return min(s.price for s in self.sizes) if self.sizes else self.price

    def unit_price(self, size_code: str | None, addon_codes: list[str] | tuple[str, ...]) -> int:
        size = self.get_size(size_code)
        base = size.price if size else self.price
        return base + sum(a.price for a in self.get_addons(addon_codes))


@dataclass(frozen=True)
class CartLine:
    id: int
    item: MenuItem
    size_code: str
    addon_codes: tuple[str, ...]
    qty: int

    @property
    def size(self) -> SizeOption | None:
        return self.item.get_size(self.size_code)

    @property
    def addons(self) -> list[Addon]:
        return self.item.get_addons(self.addon_codes)

    @property
    def unit_price(self) -> int:
        return self.item.unit_price(self.size_code, self.addon_codes)

    @property
    def total(self) -> int:
        return self.unit_price * self.qty


@dataclass(frozen=True)
class User:
    id: int
    full_name: str
    username: str | None
    phone: str | None
    last_address: str | None
    last_zone_id: int | None
    table_no: int | None
    table_set_at: datetime | None
    is_blocked: bool
    created_at: datetime | None

    @classmethod
    def from_row(cls, row) -> User:
        return cls(
            id=row["id"],
            full_name=row["full_name"],
            username=row["username"],
            phone=row["phone"],
            last_address=row["last_address"],
            last_zone_id=row["last_zone_id"],
            table_no=row["table_no"],
            table_set_at=from_db(row["table_set_at"]),
            is_blocked=bool(row["is_blocked"]),
            created_at=from_db(row["created_at"]),
        )


@dataclass(frozen=True)
class OrderItem:
    item_id: int
    title: str
    size_code: str
    size_title: str
    addon_codes: tuple[str, ...]
    addons_title: str
    unit_price: int
    qty: int

    @property
    def total(self) -> int:
        return self.unit_price * self.qty

    @property
    def full_title(self) -> str:
        parts = [self.title]
        if self.size_title:
            parts.append(self.size_title)
        title = ", ".join(parts)
        if self.addons_title:
            title += f" + {self.addons_title}"
        return title

    @classmethod
    def from_row(cls, row) -> OrderItem:
        return cls(
            item_id=row["item_id"],
            title=row["title"],
            size_code=row["size_code"],
            size_title=row["size_title"],
            addon_codes=tuple(c for c in row["addon_codes"].split(",") if c),
            addons_title=row["addons_title"],
            unit_price=row["unit_price"],
            qty=row["qty"],
        )


@dataclass(frozen=True)
class Order:
    id: int
    user_id: int
    status: OrderStatus
    method: OrderMethod
    zone_id: int | None
    address: str | None
    table_no: int | None
    customer_name: str
    phone: str | None
    comment: str | None
    scheduled_at: datetime | None  # None — «как можно скорее»
    payment_method: PaymentMethod
    is_paid: bool
    subtotal: int
    delivery_fee: int
    total: int
    reject_reason: str | None
    staff_message_id: int | None
    status_changed_by: str | None
    created_at: datetime
    updated_at: datetime
    items: tuple[OrderItem, ...] = field(default=())

    @classmethod
    def from_row(cls, row, items: tuple[OrderItem, ...] = ()) -> Order:
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            status=OrderStatus(row["status"]),
            method=OrderMethod(row["method"]),
            zone_id=row["zone_id"],
            address=row["address"],
            table_no=row["table_no"],
            customer_name=row["customer_name"],
            phone=row["phone"],
            comment=row["comment"],
            scheduled_at=from_db(row["scheduled_at"]),
            payment_method=PaymentMethod(row["payment_method"]),
            is_paid=bool(row["is_paid"]),
            subtotal=row["subtotal"],
            delivery_fee=row["delivery_fee"],
            total=row["total"],
            reject_reason=row["reject_reason"],
            staff_message_id=row["staff_message_id"],
            status_changed_by=row["status_changed_by"],
            created_at=from_db(row["created_at"]),
            updated_at=from_db(row["updated_at"]),
            items=items,
        )


@dataclass(frozen=True)
class Booking:
    id: int
    user_id: int
    starts_at: datetime
    guests: int
    name: str
    phone: str
    status: BookingStatus
    admin_messages: tuple[tuple[int, int], ...]  # (chat_id, message_id) карточек у админов
    decided_by: str | None
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> Booking:
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            starts_at=from_db(row["starts_at"]),
            guests=row["guests"],
            name=row["name"],
            phone=row["phone"],
            status=BookingStatus(row["status"]),
            admin_messages=tuple(tuple(pair) for pair in json.loads(row["admin_messages"] or "[]")),
            decided_by=row["decided_by"],
            created_at=from_db(row["created_at"]),
        )
