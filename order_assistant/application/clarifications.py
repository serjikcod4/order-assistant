from order_assistant.domain import GroundingIssueCode


MISSING_FIELD_QUESTIONS = {
    "model": "Уточните модель товара.",
    "quantity": "Уточните необходимое количество.",
    "primary_brand": "Уточните предпочтительного производителя.",
    "max_unit_price": "Уточните максимальную цену за единицу.",
    "delivery_deadline": "Уточните крайний срок доставки.",
}

QUESTION_BY_CODE = {
    GroundingIssueCode.MISSING_MODEL: "Укажите точную модель товара.",
    GroundingIssueCode.UNGROUNDED_MODEL: "Укажите точную модель товара.",
    GroundingIssueCode.MISSING_QUANTITY: "Укажите необходимое количество.",
    GroundingIssueCode.UNGROUNDED_QUANTITY: "Укажите необходимое количество.",
    GroundingIssueCode.MISSING_PRIMARY_BRAND: (
        "Укажите допустимого производителя: SKF, FAG или NSK."
    ),
    GroundingIssueCode.UNGROUNDED_PRIMARY_BRAND: (
        "Укажите допустимого производителя: SKF, FAG или NSK."
    ),
    GroundingIssueCode.UNSUPPORTED_BRAND: (
        "Укажите допустимого производителя: SKF, FAG или NSK."
    ),
    GroundingIssueCode.MISSING_PRICE: "Укажите максимальную цену за единицу.",
    GroundingIssueCode.UNGROUNDED_PRICE: (
        "Укажите максимальную цену за единицу."
    ),
    GroundingIssueCode.MISSING_DELIVERY_DEADLINE: (
        "Укажите точные дату и время доставки."
    ),
    GroundingIssueCode.AMBIGUOUS_DELIVERY_DEADLINE: (
        "Укажите точные дату и время доставки."
    ),
}

GROUNDING_QUESTION_ALIASES = {
    "model": {QUESTION_BY_CODE[GroundingIssueCode.MISSING_MODEL]},
    "quantity": {QUESTION_BY_CODE[GroundingIssueCode.MISSING_QUANTITY]},
    "primary_brand": {
        QUESTION_BY_CODE[GroundingIssueCode.MISSING_PRIMARY_BRAND]
    },
    "max_unit_price": {QUESTION_BY_CODE[GroundingIssueCode.MISSING_PRICE]},
    "delivery_deadline": {
        QUESTION_BY_CODE[GroundingIssueCode.MISSING_DELIVERY_DEADLINE]
    },
}
