"""Tests for the product model: four products, amortizing vs revolving split."""

from loanbook.products import (
    AMORTIZING_PRODUCT_TYPES,
    REVOLVING_PRODUCT_TYPES,
    ProductType,
    is_revolving,
)


class TestProductType:
    def test_products_are_exactly_the_four_consumer_credit_products(self) -> None:
        assert {product.value for product in ProductType} == {
            "personal_loan",
            "auto_loan",
            "mortgage",
            "credit_card",
        }

    def test_product_values_are_strings(self) -> None:
        assert ProductType.PERSONAL_LOAN == "personal_loan"
        assert ProductType.CREDIT_CARD == "credit_card"


class TestAmortizingRevolvingSplit:
    def test_amortizing_products_are_the_three_installment_products(self) -> None:
        assert (
            frozenset({ProductType.PERSONAL_LOAN, ProductType.AUTO_LOAN, ProductType.MORTGAGE})
            == AMORTIZING_PRODUCT_TYPES
        )

    def test_credit_card_is_the_only_revolving_product(self) -> None:
        assert frozenset({ProductType.CREDIT_CARD}) == REVOLVING_PRODUCT_TYPES

    def test_every_product_is_either_amortizing_or_revolving(self) -> None:
        assert frozenset(ProductType) == AMORTIZING_PRODUCT_TYPES | REVOLVING_PRODUCT_TYPES
        assert not AMORTIZING_PRODUCT_TYPES & REVOLVING_PRODUCT_TYPES

    def test_is_revolving_distinguishes_cards_from_installment_products(self) -> None:
        assert is_revolving(ProductType.CREDIT_CARD)
        assert not is_revolving(ProductType.PERSONAL_LOAN)
        assert not is_revolving(ProductType.AUTO_LOAN)
        assert not is_revolving(ProductType.MORTGAGE)
