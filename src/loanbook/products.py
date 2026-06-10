"""Product model: four consumer-credit products split into amortizing and revolving."""

from enum import StrEnum


class ProductType(StrEnum):
    PERSONAL_LOAN = "personal_loan"
    AUTO_LOAN = "auto_loan"
    MORTGAGE = "mortgage"
    CREDIT_CARD = "credit_card"


AMORTIZING_PRODUCT_TYPES = frozenset(
    {ProductType.PERSONAL_LOAN, ProductType.AUTO_LOAN, ProductType.MORTGAGE}
)
REVOLVING_PRODUCT_TYPES = frozenset({ProductType.CREDIT_CARD})


def is_revolving(product_type: ProductType) -> bool:
    """True for revolving credit (cards); False for installment products."""
    return product_type in REVOLVING_PRODUCT_TYPES
