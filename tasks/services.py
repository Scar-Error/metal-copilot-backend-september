from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rfq.models import Order

from tasks.models import Task


class TaskService:

    @staticmethod
    def create_supplier_assignment_task(order: Order) -> Task:
        title = f"Assign supplier for {order.rfq_number}"
        description = (
            f"Order from {order.company_name} "
            f"({order.email_subject}) has no supplier assigned."
        )
        return Task.objects.create(
            title=title,
            description=description,
            status='pending',
            order=order,
        )
