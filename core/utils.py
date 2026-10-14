from decimal import Decimal

ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
        "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
        "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

def _two_digits_to_words(n: int) -> str:
    if n == 0:
        return ""
    elif n < 20:
        return ONES[n]
    else:
        ten = TENS[n // 10]
        one = ONES[n % 10]
        return f"{ten} {one}".strip()

def _three_digits_to_words(n: int) -> str:
    hundred = n // 100
    remainder = n % 100
    parts = []
    if hundred > 0:
        parts.append(f"{ONES[hundred]} Hundred")
    if remainder > 0:
        parts.append(_two_digits_to_words(remainder))
    return " ".join(parts).strip()

def number_to_words_inr(amount) -> str:
    """
    Converts a numeric amount in INR to words following Indian numbering system
    (Crore, Lakh, Thousand, Hundred).
    E.g.
    - 3000.00 -> Rupees Three Thousand Only
    - 1500.50 -> Rupees One Thousand Five Hundred and Paise Fifty Only
    """
    if amount is None:
        return "Rupees Zero Only"

    dec_val = Decimal(str(amount)).quantize(Decimal('0.01'))
    int_part = int(dec_val)
    paise_part = int(round((dec_val - int_part) * 100))

    if int_part == 0 and paise_part == 0:
        return "Rupees Zero Only"

    parts = []

    # Indian Numbering:
    # Crores (1,00,00,000)
    crores = int_part // 10000000
    remainder = int_part % 10000000

    # Lakhs (1,00,000)
    lakhs = remainder // 100000
    remainder = remainder % 100000

    # Thousands (1,000)
    thousands = remainder // 1000
    remainder = remainder % 1000

    # Hundreds and below
    hundreds = remainder

    if crores > 0:
        parts.append(f"{_two_digits_to_words(crores)} Crore")
    if lakhs > 0:
        parts.append(f"{_two_digits_to_words(lakhs)} Lakh")
    if thousands > 0:
        parts.append(f"{_two_digits_to_words(thousands)} Thousand")
    if hundreds > 0:
        parts.append(_three_digits_to_words(hundreds))

    rupees_words = " ".join(parts).strip() or "Zero"

    paise_str = ""
    if paise_part > 0:
        paise_str = f" and Paise {_two_digits_to_words(paise_part)}"

    return f"Rupees {rupees_words}{paise_str} Only"
