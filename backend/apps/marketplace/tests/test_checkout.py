"""
Cart and cash-on-delivery checkout — Module 8.

There are no online payments: an order needs a delivery address and phone,
and no wallet is debited or credited. Failure paths must leave no order
behind.
"""

from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleViolation, ResourceGone
from apps.marketplace.models import CartItem, Order, OrderItem, OrderStatus
from apps.marketplace.services import (
    add_to_cart,
    checkout,
    clear_cart,
    remove_from_cart,
)
from apps.profiles.models import Wallet, WalletTransaction

DELIVERY = {"delivery_address": "House 12, Street 4, Gulberg III, Lahore", "delivery_phone": "03001234567"}

pytestmark = pytest.mark.django_db


def balance(user) -> Decimal:
    return Wallet.objects.get(user=user).balance


# ═══════════════════════════════════════════════════════════════════════════
# CART
# ═══════════════════════════════════════════════════════════════════════════
def test_add_to_cart(buyer, product):
    add_to_cart(buyer, product)
    assert CartItem.objects.filter(user=buyer, product=product).count() == 1


def test_adding_twice_is_not_an_error(buyer, product):
    """A digital product has no quantity — the second tap just means 'yes'."""
    add_to_cart(buyer, product)
    add_to_cart(buyer, product)
    assert CartItem.objects.filter(user=buyer).count() == 1


def test_cannot_cart_your_own_product(photographer, product):
    with pytest.raises(BusinessRuleViolation, match="your own product"):
        add_to_cart(photographer.user, product)


def test_cannot_cart_an_unpublished_product(buyer, product):
    product.is_published = False
    product.save(update_fields=["is_published"])

    with pytest.raises(ResourceGone, match="no longer available"):
        add_to_cart(buyer, product)


def test_cannot_cart_something_already_owned(funded_buyer, product):
    add_to_cart(funded_buyer, product)
    checkout(funded_buyer, **DELIVERY)

    with pytest.raises(BusinessRuleViolation, match="already own"):
        add_to_cart(funded_buyer, product)


def test_remove_and_clear(buyer, product, second_product):
    add_to_cart(buyer, product)
    add_to_cart(buyer, second_product)

    remove_from_cart(buyer, product.pk)
    assert CartItem.objects.filter(user=buyer).count() == 1

    clear_cart(buyer)
    assert CartItem.objects.filter(user=buyer).count() == 0


# ═══════════════════════════════════════════════════════════════════════════
# CHECKOUT — HAPPY PATH
# ═══════════════════════════════════════════════════════════════════════════
def test_checkout_creates_a_paid_order(funded_buyer, product):
    add_to_cart(funded_buyer, product)
    order = checkout(funded_buyer, **DELIVERY)

    assert order.status == OrderStatus.PAID
    assert order.paid_at is not None
    assert order.total == product.price
    assert order.items.count() == 1


def test_checkout_is_cash_on_delivery_and_stores_the_address(funded_buyer, product):
    add_to_cart(funded_buyer, product)
    order = checkout(funded_buyer, **DELIVERY)

    assert order.payment_method == "COD"
    assert order.delivery_address == DELIVERY["delivery_address"]
    assert order.delivery_phone == DELIVERY["delivery_phone"]


def test_checkout_does_not_touch_any_wallet(funded_buyer, product, photographer):
    before = balance(funded_buyer)
    add_to_cart(funded_buyer, product)
    checkout(funded_buyer, **DELIVERY)

    assert balance(funded_buyer) == before
    assert not WalletTransaction.objects.filter(
        txn_type__in=["PURCHASE", "EARNING"]
    ).exists()


def test_a_buyer_with_no_balance_can_order(buyer, product):
    """No credit needed: the buyer pays cash on delivery."""
    add_to_cart(buyer, product)
    order = checkout(buyer, **DELIVERY)

    assert order.status == OrderStatus.PAID
    assert order.items.count() == 1


def test_checkout_records_the_seller_share(funded_buyer, product):
    add_to_cart(funded_buyer, product)
    order = checkout(funded_buyer, **DELIVERY)
    item = order.items.first()

    expected_commission = (
        product.price * product.commission_percent / Decimal("100")
    ).quantize(Decimal("0.01"))

    assert item.commission_amount == expected_commission
    assert item.seller_earning == product.price - expected_commission


def test_checkout_snapshots_the_price(funded_buyer, product):
    add_to_cart(funded_buyer, product)
    order = checkout(funded_buyer, **DELIVERY)

    product.price = Decimal("9999.00")
    product.save(update_fields=["price"])

    item = order.items.first()
    item.refresh_from_db()
    assert item.price == Decimal("3500.00")
    assert item.product_title == "Warm Desi Wedding Presets"


def test_checkout_empties_the_cart(funded_buyer, product):
    add_to_cart(funded_buyer, product)
    checkout(funded_buyer, **DELIVERY)
    assert CartItem.objects.filter(user=funded_buyer).count() == 0


def test_checkout_bumps_product_metrics(funded_buyer, product):
    add_to_cart(funded_buyer, product)
    checkout(funded_buyer, **DELIVERY)
    product.refresh_from_db()

    assert product.sales_count == 1
    assert product.total_revenue == product.price


def test_checkout_notifies_the_seller_with_the_delivery_details(
    funded_buyer, product, photographer
):
    from apps.notifications.models import Notification

    add_to_cart(funded_buyer, product)
    checkout(funded_buyer, **DELIVERY)

    note = Notification.objects.get(
        recipient=photographer.user, notification_type="PRODUCT_SOLD"
    )
    assert DELIVERY["delivery_address"] in note.body
    assert DELIVERY["delivery_phone"] in note.body


# ═══════════════════════════════════════════════════════════════════════════
# CHECKOUT — FAILURE PATHS
# Each asserts that NOTHING moved: no order, no charge, no grant.
# ═══════════════════════════════════════════════════════════════════════════
def test_empty_cart_is_refused(funded_buyer):
    with pytest.raises(BusinessRuleViolation, match="cart is empty"):
        checkout(funded_buyer, **DELIVERY)
    assert Order.objects.count() == 0


@pytest.mark.parametrize(
    "missing", [{"delivery_address": ""}, {"delivery_phone": ""}]
)
def test_an_order_needs_an_address_and_a_phone(buyer, product, missing):
    add_to_cart(buyer, product)

    with pytest.raises(BusinessRuleViolation, match="address and phone"):
        checkout(buyer, **{**DELIVERY, **missing})

    assert Order.objects.count() == 0
    assert CartItem.objects.filter(user=buyer).count() == 1


def test_a_delisted_product_blocks_checkout_without_charging(funded_buyer, product):
    add_to_cart(funded_buyer, product)
    before = balance(funded_buyer)

    product.is_published = False
    product.save(update_fields=["is_published"])

    with pytest.raises(ResourceGone, match="no longer on sale"):
        checkout(funded_buyer, **DELIVERY)

    assert balance(funded_buyer) == before
    assert Order.objects.count() == 0


def test_already_owned_item_in_cart_blocks_checkout(funded_buyer, product, second_product):
    add_to_cart(funded_buyer, product)
    checkout(funded_buyer, **DELIVERY)

    # Force it back into the cart the way a stale client would.
    CartItem.objects.create(user=funded_buyer, product=product)
    add_to_cart(funded_buyer, second_product)
    before = balance(funded_buyer)

    with pytest.raises(BusinessRuleViolation, match="already own"):
        checkout(funded_buyer, **DELIVERY)

    assert balance(funded_buyer) == before
    assert Order.objects.filter(status=OrderStatus.PAID).count() == 1


# ═══════════════════════════════════════════════════════════════════════════
# IDEMPOTENCY
# ═══════════════════════════════════════════════════════════════════════════
def test_the_same_key_returns_the_same_order(funded_buyer, product):
    add_to_cart(funded_buyer, product)
    first = checkout(funded_buyer, **DELIVERY, idempotency_key="tap-1")
    second = checkout(funded_buyer, **DELIVERY, idempotency_key="tap-1")

    assert first.pk == second.pk
    assert Order.objects.count() == 1


def test_a_double_tap_places_one_order(funded_buyer, product):
    add_to_cart(funded_buyer, product)

    checkout(funded_buyer, **DELIVERY, idempotency_key="tap-1")
    checkout(funded_buyer, **DELIVERY, idempotency_key="tap-1")

    assert Order.objects.count() == 1


def test_a_different_key_is_a_different_purchase(funded_buyer, product, second_product):
    add_to_cart(funded_buyer, product)
    first = checkout(funded_buyer, **DELIVERY, idempotency_key="tap-1")

    add_to_cart(funded_buyer, second_product)
    second = checkout(funded_buyer, **DELIVERY, idempotency_key="tap-2")

    assert first.pk != second.pk
    assert Order.objects.count() == 2
