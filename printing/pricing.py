"""Price calculation for print requests (thesis section 4.5).

    pagePrice  = basePagePrice x colorCoefficient x paperCoefficient x duplexCoefficient
    totalPrice = documentPages x copies x pagePrice

All arithmetic uses Decimal so that money values are exact. The total is
rounded once, at the end, to whole cents using ROUND_HALF_UP.

This module has no Django dependency so that it can be unit tested on its own.
"""

from decimal import ROUND_HALF_UP, Decimal

BASE_PAGE_PRICE = Decimal("0.10")  # EUR, black-and-white A4 one-sided

COLOR_COEFFICIENTS = {
    "BW": Decimal("1.00"),
    "COLOR": Decimal("2.00"),
}

PAPER_COEFFICIENTS = {
    "A4": Decimal("1.00"),
    "A3": Decimal("1.80"),
}

DUPLEX_COEFFICIENTS = {
    "ONE_SIDED": Decimal("1.00"),
    "DOUBLE_SIDED": Decimal("0.90"),
}

CENT = Decimal("0.01")


def calculate_page_price(color_mode: str, paper_format: str, duplex_mode: str) -> Decimal:
    try:
        return (
            BASE_PAGE_PRICE
            * COLOR_COEFFICIENTS[color_mode]
            * PAPER_COEFFICIENTS[paper_format]
            * DUPLEX_COEFFICIENTS[duplex_mode]
        )
    except KeyError as exc:
        raise ValueError(f"Unknown print setting: {exc.args[0]}") from exc


def calculate_total_price(
    document_pages: int,
    copies: int,
    color_mode: str,
    paper_format: str,
    duplex_mode: str,
) -> Decimal:
    if document_pages < 1 or copies < 1:
        raise ValueError("Pages and copies must be positive.")

    page_price = calculate_page_price(color_mode, paper_format, duplex_mode)
    total = Decimal(document_pages) * Decimal(copies) * page_price
    return total.quantize(CENT, rounding=ROUND_HALF_UP)
